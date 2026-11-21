# The suite that passes

*A musing on measuring whether a test suite can fail. 2026-11-21. Not an ADR: nothing here is implemented, and the numbers are a starting point for an argument, not a result.*

Tests are now cheap to write. An agent can produce a hundred of them between two prompts, and the visible signals reward that: the diff is larger, the line count is larger, the suite still passes. What none of those signals answer is the question that matters, which is whether the suite would notice if a behaviour broke. This document is about measuring that, starting from mutation testing and then asking what else is worth the compute.

I have marked claims as measured, reasoned, or speculation. Measured means I ran it or read it in this repository today. Reasoned means arithmetic or an inference from measured facts. Speculation means a guess I have not tested. Where a number is unknown I say it is unmeasured and say how I would measure it.

## What this repository can say about its own tests

| Fact | Value | How it is known |
|-|-|-|
| Unit tier size | 1,247 passed, 11 skipped, 23 deselected | Measured 2026-11-20: `uv run pytest -q -m "not e2e and not staging"` |
| Unit tier wall time | 84.36 s | Same run, on a laptop-class arm64 machine |
| Source under test in the CLI | 9,740 lines across 37 modules | Measured by line count under `cli/cove` |
| Test modules defining tests | 47 | Measured by scanning `cli/tests` |
| Go tests | 19 test functions in `compose/secrets-guard` | Measured by scan |
| Workflow paths in the coverage matrix | 109 | Measured from `docs/test-coverage-matrix.yaml` |
| Paths with a `corner` case marked executable | 12 of 109 (83 skip, 14 manual) | Measured from the same file |
| Code that reads the matrix | None | Measured by grep; only plans and docs mention it |
| Coverage measurement in the CLI | None installed | Measured: no `pytest-cov`, no `--cov` in any workflow |

The coverage matrix is the closest thing the repository has to a claim about test effectiveness. It lists 109 workflow paths with a `blast_radius` of high (68), medium (24), or low (17), and marks each of four categories as `executable`, `skip`, or `manual`. Nobody and nothing checks whether an `executable` cell corresponds to a test that would fail if the path broke. The matrix records an intention. The intention is probably mostly honest, because the tests were written alongside it, but it has the same epistemic status as a comment.

The repository does not measure line coverage either. That is worth stating plainly, because the argument against coverage as an effectiveness proxy can obscure the fact that the baseline is lower than the argument assumes: there is no coverage number here to argue about.

### The defect that prompted this

On 2026-11-20, three tests asserted that a service-account token selects the SDK-backed secret provider. They passed on the operator's machine, where the optional `onepassword` extra happened to be installed, and failed on a clean checkout. The fix landed in three small pull requests: #186, "test(secrets): the SDK preference test must not depend on the host"; #187, "test(secrets): the same host dependence in the provider test"; #188, "test(secrets): the last host-dependent provider test". Each fix made the test declare the package instead of inheriting it.

The mechanism matters more than the count. Provider selection takes two inputs: the token and the package. The suite had a test for token present with the package, because the operator's machine supplied the package, and a test for token absent. It had no test for token present with the package absent, which is the combination that decides whether the token alone is enough.

Line coverage is nearly blind to this. The failing run covered the CLI return, the passing run covered the SDK return, and the suite as a whole covered both. The covered set barely changes between the two hosts, and no line is missing. Branch coverage is closer but still not sufficient: with the package installed, the availability check is true in every test that sets a token, so the false side of that check with a token present is never taken.

Here is a mutant a tool would generate on its first pass: replace `if token and _sdk_available():` with `if token:`. Walk the suite. The SDK selection test patches availability to true. The no-token test never reaches the condition. The direct `OnePasswordSdk().validate` test does not call `provider_for` at all. The routing test patches availability to true. Every test still passes, so the mutant survives, and the survivor names the exact rule the suite fails to pin. I checked this by hand rather than with a tool, so treat it as reasoned. It is the kind of result a run would produce, and it is the reason I think the run is worth doing.

On a machine without the package the original test fails, which is how the defect was found. On a machine with it, the suite is green and the rule is unpinned. The test inherited an external resource it never declared, which is the shape the test-smell literature calls a Mystery Guest, even though the textbook examples are files and databases rather than installed packages.

## Coverage counts execution, not discrimination

A coverage tool records which statements the test process reached. That is a fact about execution. An assertion is a claim about a set of inputs and a set of wrong implementations: it says that if the code were wrong in one of these ways, this observation would differ. The two have different shapes. Coverage is a set of lines. A test's power is a set of wrong implementations it excludes. A line can be covered in every run while the input combination that would expose the rule is never constructed.

The SDK case is a clean demonstration. `provider_for` reads two inputs and returns one of two providers. The suite covered both returns across two tests, so the line set was complete. The missing thing was a combination: token set, package absent. Coverage has no vocabulary for a missing combination, because no line is missing. The assertion's truth was a function of the machine, so the test's verdict was too.

This is not a rare edge. Adding a test never lowers line coverage, and a test that calls a line raises it, whether or not its assertion could ever fail. A test with no assertion raises it. A test whose assertion restates the implementation raises it. A test that asserts `result is not None` on a function that never returns `None` raises it. The metric cannot distinguish these from a test that pins the behaviour, because the metric is about the call graph, not about the space of wrong implementations the assertion excludes.

LLM-generated tests are shaped by the same gradient. When the request is "raise coverage" or "add tests for this module", the cheapest satisfying output is a test that exercises the code and asserts something true of the current implementation. The request carries no signal about discrimination, and judging discrimination would require knowing which wrong implementations are plausible. The result is exactly the reported pattern: more lines covered, the same defect escape rate. The tests are real tests in the sense that they run. They are not tests in the sense that they could fail for the right reason.

Branch coverage narrows the gap without closing it. It forces both directions of a conditional to execute somewhere in the suite, which catches the common case of a one-sided test. It still counts reaching the branch, not distinguishing the right outcome from a plausible wrong one, and it says nothing about a branch that needs two inputs to reach.

A better question is: if I replaced this function with a plausible wrong version, would anything fail? That question has a mechanical answer, which is mutation testing.

## Mutation testing changes the question

A mutant is a copy of the program with one small, mechanical change: `<` becomes `<=`, `+` becomes `-`, a returned value becomes `0` or `None` or `""`, a statement is deleted, a boolean is inverted. The suite runs against the mutant. If at least one test fails, the mutant is killed. If every test passes, the mutant survived, which means no test in the suite observed the difference. The survivor is a precise, reproducible statement about a behaviour the suite does not pin.

Two ratios get confused, and the confusion matters:

- **Mutation score** is killed divided by killed plus survived. It asks how much of the behaviour the suite can discriminate.
- **Mutation coverage** is mutants reached by at least one test divided by all mutants. It asks how much of the code the suite touches.

Tools disagree about names. PIT's reports distinguish mutation coverage from test strength, where test strength excludes uncovered mutants from the denominator ([pitest issue #128](https://github.com/hcoles/pitest/issues/128)). Stryker reports `NoCoverage` as its own mutant status, distinct from `Survived` ([Stryker configuration](https://stryker-mutator.io/docs/stryker-js/configuration/)). Whatever the labels, the distinction to preserve is whether uncovered mutants sit in the denominator. A suite can reach every mutant and kill few of them, which is the machine-readable version of "the tests run the code and assert nothing".

Mutation testing also has known noise. Some mutants are equivalent: they change the syntax and not the semantics, so no test can kill them, and deciding equivalence is undecidable in general ([Empirical Evaluation of Manually Created Equivalent Mutants](https://arxiv.org/html/2404.09241v1)). Some are unviable and fail to compile or import. Some loop forever and are killed by a timeout. A mature run reports all four outcomes, and a survivor is a question for a human, not a verdict.

### The tools and what they cost

| Tool | Language | Cost controls | The catch |
|-|-|-|-|
| [mutmut](https://mutmut.readthedocs.io/en/latest/) | Python | Caches results between runs, selects the tests that reach a mutant, parallel fork workers | POSIX only; monkeypatch-heavy suites can make workers hang or misreport |
| [cosmic-ray](https://cosmic-ray.readthedocs.io/en/latest/concepts.html) | Python | SQLite session survives interruption, local or HTTP-distributed workers, timeout per mutant | More setup; no documented per-test selection, so each mutant tends to pay for a broader run |
| [Stryker](https://stryker-mutator.io/docs/stryker-js/incremental/) | JS/TS | Per-test coverage analysis, incremental result file, mutation ranges by line, configurable thresholds | Copies the project into a sandbox; needs a Node toolchain |
| [PIT](https://pitest.org/quickstart/incremental_analysis/) | Java | Bytecode mutation, coverage-based test selection, incremental analysis with a history file | JVM only; timeouts need tuning on slow machines |
| [cargo-mutants](https://mutants.rs/in-diff.html) | Rust | `--in-diff` for changed lines, `--shard k/n` across machines, type-aware mutant generation | Compiles per mutant; the project must be Rust |

The cost model is the same everywhere. You run the test suite once per mutant, minus whatever selection and caching remove. The cargo-mutants documentation states it directly: total CPU is roughly `N_MUTANTS * (incremental build + test)` plus per-shard startup ([sharding](https://mutants.rs/shards.html)). PIT's own FAQ says mutation testing "can take quite some time" and recommends limiting analysis to changed code ([PIT FAQ](https://pitest.org/faq/)). No tool makes the fundamental trade disappear. They make it fit inside a budget.

### The arithmetic for this repository

Measured: one full unit-tier run is 84.36 s. A proxy scan of `cli/cove` (comparisons, boolean operators, negations, returns, numeric constants, binary operations) finds 2,979 candidate mutation sites, about 306 per 1,000 lines. That is not a mutant count: real tools apply operators selectively and skip some sites, so the true number is lower. Call it 1,000 to 3,000 mutants for the CLI, and treat that as reasoned, not measured.

At 84 s per mutant, serial, with no selection or caching:

- 1,000 mutants: about 23 hours.
- 3,000 mutants: about 70 hours.

With four parallel workers, that becomes roughly 6 to 18 hours, on one machine, for one run. On a single CI runner that is a nightly job, not a pull-request check. The two blocking workflows in this repository cap at ten minutes each, so a mutation job cannot share their shape without either a much longer timeout or aggressive scoping. It also explains why whole-repo mutation runs are rare in practice even when teams like the idea: the first run costs more than the feature that prompted it.

Selection changes the arithmetic by orders of magnitude, and this is the useful part. `cli/tests/test_pins.py` is seven tests that finish in 0.21 s. A mutant confined to `pins.py` only needs those seven tests, so a hundred mutants cost about twenty seconds plus process overhead, not two and a half hours. At the other end, `tunnel.py` is 1,159 lines with 471 proxy sites and 108 tests, and `test_tunnel.py` is the largest test module in the tree.

The unmeasured quantities are the ones that decide whether this is worth building: how many mutants the real tools generate here, how many survive, how long a diff-scoped run takes, and what fraction of survivors are equivalent. The next section is about the cheap way to find out.

## The cheaper signals, and what each one cannot see

Mutation testing is the most direct measurement, not the only useful one. These pair with it because each covers a blind spot the others have.

### Diff-scoped mutation

This is the only version that fits a pull request. cargo-mutants has `--in-diff`, PIT has incremental analysis with a history file, Stryker has incremental mode plus `--mutate` ranges down to `file.js:5-7`, and mutmut accepts module or function patterns. The run mutates only lines the diff touched, which turns hours into minutes on a normal change.

It catches new weak tests on new code, which is the failure mode LLM-written tests produce most often. It cannot see collateral damage: cargo-mutants says explicitly that an edit in one region can leave code elsewhere less well tested, and that a diff touching only tests produces no mutants at all ([in-diff caution](https://mutants.rs/in-diff.html)). It is also easy to game by touching code in ways that avoid mutation, or by adding `# pragma: no mutate` where a survivor is inconvenient. The allowlist has to be reviewed like code.

### Assertion strength and test smells

The research catalogue is concrete. tsDetect detects 19 test smells in Java, including Assertion Roulette, Empty Test, Redundant Assertion, and Mystery Guest ([tsDetect](https://testsmells.org/pages/testsmells.html), [FSE 2020 paper](https://testsmells.org/assets/publications/FSE2020_TechnicalPaper.pdf)). Python has no equally mature detector, so the cheap version here is a set of local heuristics: a test with no assertion, a test that asserts only `is not None`, a test that asserts on a mock's call rather than on the result, a test whose expected value is computed with the same expression as the implementation.

An unasserted or tautological test is a defect mutation testing catches only accidentally, when a mutant happens to land in the expression the test does assert. The smell detector catches it directly. What the detector cannot see is a test that asserts a precise wrong constant: mutation testing kills that test (it fails on the mutant for the wrong reason), and the detector passes it. Neither tool understands intent.

The SDK test is exactly this shape: it depended on an installed package it never declared. A local heuristic for "reads process state without monkeypatching it" would have flagged it directly, and that heuristic is cheaper to build than a full smell detector.

### Property-based testing yield

Hypothesis generates inputs from a strategy and shrinks a failing case to a small one; its ghostwriter can draft a property test from a function signature ([Hypothesis ghostwriter](https://hypothesis.readthedocs.io/en/latest/_modules/hypothesis/extra/ghostwriter.html)). The useful metric is not the number of property tests but the number of distinct falsifying examples they produce and the size of the shrunk counterexample. A property that finds nothing new for a quarter is either correct or vacuous, and the counterexample history tells you which.

Property tests catch input-space holes that example tests miss, especially in parsers and normalizers. They cannot see a property that encodes the implementation, which is the same restatement failure as an example test with better syntax. They can be gamed by asserting only "does not raise", which is a real property but a weak one.

### Flaky rate

Flakiness is the signal that would have caught the 2026-11-20 defect without any mutation run. Google's write-up on flaky tests documents the problem at its scale and the mitigation machinery a large test system needs ([Flaky Tests at Google](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)). The local version is cheap: rerun each test N times on a clean environment, or track pass/fail per test across runs and count transitions.

Flaky rate catches host dependence, order dependence, and timing assumptions. It cannot see a test that is stable and wrong. It is trivially gamed by retries, which is why the metric has to count retries, not just final status: a suite with `--reruns 3` looks stable and hides the same defect.

### Defect escape from incident records

DORA's change failure rate is the percentage of changes that cause degraded service and require remediation ([DORA four keys](https://dora.dev/guides/dora-metrics-four-keys/)). The test-specific version is narrower and more useful: of the incidents and near misses in a period, how many had a root cause a test could have caught, and what fraction of merged changes is that? The 2026-11-20 case was caught by a clean checkout before merge, so it belongs in the near-miss population. Counting it is the point, because it is exactly the defect the suite failed to catch.

This signal catches the defect classes that actually reach production, which no mutation run weights for you. It cannot see defects caught in review or never noticed. It is gamed by the classification step: anything can be declared "not testable", so the classification should be recorded with the incident and reviewed. The prerequisite is a ledger that does not exist here yet. Incidents and near misses currently live as prose in plans, tech-debt notes, and commit messages, with no queryable date and root cause, so the metric needs that table before it can be computed at all.

### Adversarial generation

An LLM given a diff can be asked for a test that passes on the parent commit and fails on the change, or given a surviving mutant and asked for a test that kills it. MuTAP does the second mechanically, using surviving mutants as feedback for test generation ([MuTAP](https://github.com/ExpertiseModel/MuTAP)). This catches semantic gaps that mutation operators miss: a wrong error message, a wrong ordering, a wrong default that the operators do not generate.

It cannot see anything the model does not think of, and it is non-deterministic, so the yield varies run to run. It is gamed by a test that fails for the wrong reason, for example one that asserts on a mock call or an exact string that the patch happened to change. Every generated test needs a human to confirm that its failure is the intended one. The 2023 TSE study of LLM test generation is the background here: across 25 npm packages its generated tests reached a median statement coverage of 70.2% and branch coverage of 52.8%, which is precisely the kind of result that looks like an answer to "are the tests good" and is not ([Schäfer et al.](https://arxiv.org/abs/2302.06527)).

## A Cove-shaped offering

Cove already has the pieces: a CLI that owns state paths and loud failures, a Forgejo Actions runner that executes containerized jobs, a nightly automation pattern at 06:00, SQLite used elsewhere for durable state, and an operating convention that calls for SPC-style control charts for quality. The convention has no implementation in this repository today; I checked, and any control chart here would be new code rather than a wrapper around an existing script.

Three sizes are possible.

| Size | Shape | Build cost | What it buys | What it costs you |
|-|-|-|-|-|
| Script | One Python file under `scripts/quality/`, a SQLite file, a scheduled automation | About a day | Survivor rate on a fixed module list, history, no gate | Another script to maintain; no shared vocabulary |
| CLI subcommand | `cove quality tests`, pinned schema, `--diff`, `--check`, JSON output | About a week | One command for any project on the machine; state under the data root; plays with the existing CLI conventions | A public surface that has to keep working |
| Service | A `quality` compose profile, a pages.cove dashboard, a Forgejo status check | Weeks | Shared history and a UI for several projects | A schema and a UI frozen before the metric is calibrated |

I would build the script first and promote it to the CLI only after it has produced four weeks of runs on `main`. The engine is the easy part; the module allowlist, the equivalent-mutant triage, and the runtime budget are the parts that need evidence. A service at this stage freezes decisions that the first ten runs would overturn.

The concrete shape I would aim for, in CLI form:

- **Command:** `cove quality tests [--diff BASE] [--module NAME] [--budget-seconds N] [--check]`. With no arguments it mutates the configured anchor modules. With `--diff` it maps changed lines to modules and mutates only those.
- **Where it runs:** a Forgejo Actions workflow on the existing runner, scheduled after the 06:00 age gate rather than at the same minute, because both jobs compete for the same host and there is one runner. A bb script automation is the alternative, and it is already the pattern for deterministic scheduled work.
- **What it stores:** `${COVE_DATA_ROOT}/quality/tests.db`, with one row per run (commit, tool version, scope, suite seconds, budget), one per mutant (module, line, operator, status, duration), and one per module score (generated, killed, survived, uncovered, timeout, allowlisted). The tool version belongs in the run row because a score is not comparable across versions.
- **What it prints:** a module table with mutants, killed, survived, score, and the delta against the last `main` run; a second table of the highest-blast-radius survivors, joined to the coverage matrix where a module maps to a path; one line for the trend. The denominator is printed every time.
- **What gates:** nothing, at first. If a gate ever exists it is the diff-scoped run, advisory, capped at a fixed number of minutes, and a timeout reports "not measured" rather than "pass". A nightly run reports. A whole-repo percentage never gates.
- **What it must not do:** touch the live or staging tiers, write to `main`, or turn a timeout into a green result.

## The measurement design

The trend line should be mutation score on a frozen anchor set of modules, with the tool version, mutator set, and denominator printed beside it. Not a score across all code. A global score moves for reasons that have nothing to do with suite quality: new untested code pulls it down, new well-tested code pulls it up, and neither tells you whether the tests you already had got better.

A second line is more actionable: the absolute count of surviving mutants per 1,000 changed lines per week. Absolute survivors, not a ratio, because a developer can open a survivor and fix it, and because the count does not improve when unrelated code is added.

A regression is one of two events. Either a module's score falls below its own baseline mean minus two standard deviations (the workstation's stated N=10, 2-sigma convention for personal projects), or a line changed in the last week produces a survivor. The second is the sharper signal and the one worth acting on. A one-point drop in a global percentage is not a regression; it is noise until proven otherwise.

The growth artifact is the main trap. Mutation score is a ratio whose denominator grows with the code, so the same suite quality yields a lower score as the codebase grows unless the new code is tested as well as the old. Freezing the anchor set for a quarter, reporting new modules separately, and printing the denominator all reduce the artifact. Comparing scores across tool versions or mutator sets does not reduce it; it manufactures a trend. Those comparisons should be treated as invalid, not as a small caveat.

Thresholds are where this becomes a target. A global "80% mutation score" gate invites three reliable responses: write assertion-free tests that happen to kill mutants, add `# pragma: no mutate` to the survivors, or move the hard modules out of the anchor set. The first is the failure mode this whole document is about, arriving through the back door. The counter is to gate on a property that cannot be satisfied without a real test: zero new survivors on changed lines, with every survivor either fixed or entered in an allowlist with a reason and a reviewer's name. The allowlist is both the pressure valve and the audit trail, and its growth rate is itself a signal worth watching.

SPC conventions apply to the rest. The first ten runs are a baseline, not a trend. One point outside two sigma is a reason to look, not a reason to fail a build. A tool version change starts a new series.

## What would make this a bad idea

The cost is real. Twenty-three to seventy CPU-hours for one serial whole-repo run at today's suite speed, repeated nightly, is a measurable fraction of one machine. Diff scoping and per-module budgets are not optimizations here; they are the condition for the idea being viable at all.

The confidence can be false. Mutation score measures the imagination of the mutator set, not correctness. A suite can kill every operator mutant and still ship the SDK defect, because that defect is about which input the test controls, not which statement changed. Calling the number "test quality" would overclaim in a way that is hard to walk back.

Equivalent mutants accumulate as judgment debt. Equivalence is undecidable, so every allowlist entry is a human call that decays as the code changes. At a thousand mutants, even a five percent equivalent rate is fifty unreviewed judgments (the rate is speculation; nothing in this repository measures it yet). The tool's upkeep does not stop at installation.

The tool itself needs maintenance. This repository has Python, Go, and shell, plus a pinned-artifact discipline and a bundling step for the CLI. A mutation runner adds another pinned artifact, another version to bump, and another source of configuration drift. Python's dynamic imports and the suite's heavy monkeypatching may produce unviable mutants and hung workers, which is exactly the kind of failure that makes a nightly job untrusted and then ignored.

The deepest objection is fit. Most of this repository's defects are integration-shaped: host state, container state, Ansible ordering, DNS resolution, certificate drift. Statement mutation on Python functions is a poor instrument for that population. The 2026-11-20 defect is the counterexample that keeps the idea alive: it was a unit-level test that measured the host, and a clean-environment run or a flaky-rate count would have caught it without mutation testing at all. The honest conclusion is that mutation testing is one instrument among several, and probably not the first one to build.

There is also a category error waiting at the end. The coverage matrix is organized by workflow path and blast radius; mutation testing reports by file and line. A high score in `tunnel.py` says nothing about the "non-TTY bare up fails loud" path unless the tests for that path exist and assert the right thing. Merging the two into one dashboard would create a number that looks like it covers both and covers neither.

None of this kills the idea for me. It changes the order. The cheap measurements are worth building because they are cheap and because the alternative is guessing. The expensive one should be earned by evidence that the cheap ones cannot supply.

## What I would measure first

Three experiments, each a day or less, before any command is designed.

1. Run mutmut on two modules of different shape, `pins.py` and `update.py`, and record generated, killed, survived, and wall time. Triage the first five survivors by hand and classify each as missing test, equivalent mutant, or dead code. This answers whether the score is meaningful here and what the equivalent rate looks like. All of it is unmeasured today.
2. Replay the 2026-11-20 defect on a clean environment without the optional extra: run the three pre-fix tests and record pass/fail, then run the fixed tests on both a bare and an equipped environment. This produces a concrete host-dependent count and validates the flaky-rate signal against a known defect.
3. Instrument the unit tier for per-test duration and pass/fail history over twenty runs, then compute the flaky candidate list from reruns. This is the cheapest signal and the one most likely to catch this repository's actual defect class.

If the first experiment shows a survivor rate that a developer would act on, and the third shows the host-dependence class repeating, then the CLI subcommand is worth a week. If the survivors are mostly equivalent or trivial, the honest move is to keep the flaky-rate report and skip mutation testing for now.

## Sources

- [mutmut documentation](https://mutmut.readthedocs.io/en/latest/)
- [Cosmic Ray concepts](https://cosmic-ray.readthedocs.io/en/latest/concepts.html)
- [StrykerJS incremental mode](https://stryker-mutator.io/docs/stryker-js/incremental/) and [configuration](https://stryker-mutator.io/docs/stryker-js/configuration/)
- [PIT FAQ](https://pitest.org/faq/), [mutators](https://pitest.org/quickstart/mutators/), [incremental analysis](https://pitest.org/quickstart/incremental_analysis/)
- [cargo-mutants: mutation patterns](https://mutants.rs/mutants.html), [in-diff](https://mutants.rs/in-diff.html), [sharding](https://mutants.rs/shards.html)
- [An Empirical Evaluation of Manually Created Equivalent Mutants](https://arxiv.org/html/2404.09241v1)
- [tsDetect test smell catalogue](https://testsmells.org/pages/testsmells.html) and [FSE 2020 paper](https://testsmells.org/assets/publications/FSE2020_TechnicalPaper.pdf)
- [Schäfer et al., An Empirical Evaluation of Using Large Language Models for Automated Unit Test Generation](https://arxiv.org/abs/2302.06527)
- [MuTAP](https://github.com/ExpertiseModel/MuTAP)
- [Hypothesis ghostwriter](https://hypothesis.readthedocs.io/en/latest/_modules/hypothesis/extra/ghostwriter.html)
- [Flaky Tests at Google and How We Mitigate Them](https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html)
- [DORA four keys](https://dora.dev/guides/dora-metrics-four-keys/)
