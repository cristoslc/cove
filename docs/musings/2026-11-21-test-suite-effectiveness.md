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

## Addendum (2026-11-21): cadence, selection cost, and a correction

*Addendum to a published musing. What changed and why: a peer measured the worked survivor and it is killed at HEAD, the runtime is a range rather than a point, and the defect-population sentence is marked as an unsettled hypothesis. Everything above this section is unchanged so the published argument stays comparable.*

### The worked survivor was killed

The published text says that replacing `if token and _sdk_available():` with `if token:` leaves every test passing. It does not. At `6293912`, `test_a_token_without_the_sdk_falls_back_to_the_cli` in `cli/tests/test_provider_selection.py` sets a token and stubs `_sdk_available` to `False`, then asserts the CLI provider. The mutant returns the SDK provider and the test fails. I reproduced it in a clean copy: one failed, nineteen passed across the three provider test modules.

The peer swept eight mutants over `provider_for` and `_sdk_available`: six killed, two survived. The survivors are the interesting part. `_sdk_available()` hardcoded to `True` survives, and hardcoded to `False` survives. I reproduced the first against the full unit tier with the function's body replaced by `return True`: 1,247 passed, 11 skipped, 23 deselected. The body is never executed by the suite, because every test that reaches it stubs it. The caller is well pinned and the implementation behind the seam is unconstrained.

That is a better example for this document than the one it replaces, because it shows the converse of the coverage failure. Coverage asks whether the line ran. This gap is a line that ran in no test at all while every caller was tested. A stub at the seam can pin the call and leave the thing behind the seam free to be wrong. The survivor to cite is `_sdk_available: always True`, not `provider_for: drop the SDK check`.

The motivating incident stands. The 2026-11-20 tests inherited the package from the host and changed verdict between machines, and the fixes declared it. But the incident is motivation, not proof of that mutant.

The second experiment in "What I would measure first" also needs a fix. The peer reports that at `955e8e8` the suite already fails three tests on a host without the extra, for an unrelated token-parse reason, so a pass/fail count there measures the fake token rather than the defect. Run the same test file on a bare and an equipped environment and diff the verdicts, or use the mutation sweep above.

### The cost is a range

The table's 84.36 s is one cold run. The same tier measured 67.23 s and 54.11 s in the peer's runs, and 63.92 s in my clean copy. Read it as roughly 55 to 85 seconds depending on machine and cache. A second operator set counted 3,089 proxy sites against my 2,979, so read roughly 3,000. Neither correction moves the conclusion: a serial sweep of 1,000 to 3,000 mutants is tens of CPU-hours.

### Three tiers are the only shape that fits

At 55 to 85 seconds per full-suite run, 1,000 mutants cost 15 to 24 CPU-hours and 3,000 cost 46 to 71. The two blocking pull-request workflows in this repository cap at ten minutes, on one runner. A per-push whole-repo mutation run cannot fit in that envelope. The tiers below are not a preference; they are the only shape that fits.

- **Pull request.** Run only when Python source or tests change. Mutate changed lines in the touched modules, and run only the tests that reach each mutant. Cap the job at five to ten minutes. Keep it advisory. Cancel superseded runs on the same pull request. Skip docs, compose, and Ansible-only changes.
- **Nightly.** The anchor set of modules, budgeted or sharded, off the critical path. This is the trend line.
- **Periodic full sweep.** Weekly or monthly. It catches collateral damage from edits elsewhere and test-only changes, which a diff-scoped run cannot see. This is the run that makes the other two honest.

The existing unit, integration, and staging tiers do not change. Mutation sits beside them.

### Selection levers and their costs

| Lever | What it saves | What it costs |
|-|-|-|
| Test selection | Runs only tests that reach the mutant; the largest saving | Needs per-test coverage; import-time and static mutants fall back to the whole suite |
| Diff-scoped mutants | Only changed lines, so a normal pull request is minutes | Misses collateral damage; a test-only diff produces no mutants |
| Anchor-set mutants | A stable, comparable trend | Blind to regressions outside the set |
| Sampling | A bounded run when the set is large | Noisy score; rare survivors hide |
| Caching or incremental results | Reuses unchanged results across runs | Stale when dependencies or configuration change; tools differ in what they detect |
| Time budget | A hard cap on wall time | The score covers only part of the set; the rest must report "not measured", never pass |

The mitigations are a persistent survivor ledger so a diff run does not forget old survivors, a periodic full sweep, and a printed scope and denominator on every report. Never compare a sampled score to a full one; that manufactures a trend.

### Survivors need triage before they are work

A survivor list is a candidate list. In the peer's 20-site sample, nine survivors reduced to six real gaps: two were harness artifacts (a docstring line and an error-message string) and one was an equivalent mutant behind an existing guard. A report that does not classify survivors will send someone chasing a comment.

Classify each survivor at minimum as real gap, equivalent, unreachable behind a guard, or harness artifact. A docstring and string-literal mask is an afternoon's work and belongs in the first commit. The `_sdk_available` survivors above are real gaps, which is what makes them useful.

### Prior art

Execution is solved per ecosystem: mutmut and cosmic-ray for Python, Stryker for JS/TS, PIT for Java, cargo-mutants for Rust. Diff-scoped and incremental modes are standard.

Reporting and pull-request integration are partly solved. [Stryker Dashboard](https://stryker-mutator.io/docs/General/dashboard/) hosts reports for any framework that emits the mutation testing report schema, free for open source, with GitHub login. [arcmutate](https://docs.arcmutate.com/docs/github/overview.html) mutates only the lines a pull request changes and annotates survivors in the GitHub diff; it is commercial, PIT, and GitHub. Neither GitLab nor SonarQube runs mutants natively. Predictive mutation testing is research ([MutationBERT](https://clairelegoues.com/assets/papers/jainContextualPMT.pdf)), not a product.

The delta for Cove is cross-language orchestration, Forgejo-native reporting, and a local budget policy. That is glue, not novel science, which is another reason the script comes first.

### A hard constraint: run against a copy

`uv run` rewrites `cli/uv.lock` when the lock is stale; it did so in this worktree during the measurements for the original document. A runner that executes the suite thousands of times will thrash any file the toolchain touches. A crash between rewriting a source file and restoring it can leave a mutant in the tree, and a later `git commit -a` would carry it into history.

Run mutation against a copy or a clone, never against a working tree someone is editing. Record the commit and the tool version with every run, because a score that cannot be attributed to a commit is useless once trunk moves.

### The defect-population claim is still a hypothesis

The published text says:

> Most of this repository's defects are integration-shaped: host state, container state, Ansible ordering, DNS resolution, certificate drift.

That is an impression from a small sample of incidents and near misses, not a count. The peer cross-check did not test it: the audit covered eight projects and measured mutation behavior, not a classification of this repository's defects. One peer conversation cannot settle a claim about a defect population, and neither can this addendum.

Treat the sentence as a working hypothesis. Settling it needs an incident ledger with a date and a root-cause class, which the defect-escape signal needs anyway. Until then, the recommendation to build the cheap signals first stands on cost, not on that classification.

### Evidence the published version was missing

The peer's audit of eight projects found line coverage overstating discriminating power by 15 to 20 points, including a project with 89.6% weighted coverage against a 69.1% mutation score and six modules at 100% line coverage. The same result has been measured at scale:

- Inozemtseva and Holmes found only a low to moderate correlation between coverage and effectiveness once suite size was controlled, and stronger coverage types added no insight ([ICSE 2014](https://www.cs.ubc.ca/~rtholmes/papers/icse_2014_inozemtseva.pdf)).
- Just et al. found mutant detection a good proxy for real-fault detection, and the relationship held independently of coverage ([FSE 2014](https://homes.cs.washington.edu/~rjust/publ/mutants_real_faults_fse_2014.pdf)).
- Zhang and Mesbah found assertion count strongly correlated with effectiveness even with suite size controlled, which is the empirical backing the assertion-strength section lacked ([FSE 2015](https://people.ece.ubc.ca/amesbah/resources/papers/fse15.pdf)).
- ASSENT found mutation score among the best metrics tested, while warning that substituting mutants for real faults overestimates effectiveness by more than 20% ([TOSEM 2024](https://dl.acm.org/doi/10.1145/3635713)). That is the quantitative form of this document's false-confidence objection.
- Petrović et al. analyzed almost 15 million mutants at Google and found that developers using mutation testing wrote more tests, reduced survivors, and that mutants were coupled with real faults ([ICSE 2021](https://arxiv.org/abs/2103.07189)).

## First measurements

*Measured 2026-11-21 (UTC) on an arm64 laptop, four workers. Tool: mutmut 3.8.1, run from a throwaway mirror of `cli/` so the project's own dependency set and working tree stayed untouched. Nothing under `cli/` was edited to make the tool cooperate.*

Experiment 1 is now a measured result instead of a reasoned one. The numbers below are observed; where I extrapolate, I say so.

### What ran

| | `cli/cove/pins.py` | `cli/cove/update.py` |
|-|-|-|
| Module size | 182 lines | 548 lines |
| Test module | `tests/test_pins.py` | `tests/test_update.py` |
| Tests in that module | 7 | 36 |
| That module alone, pytest | 7 passed in 0.37 s | 36 passed in 0.63 s |
| Mutants generated | 343 | 573 |
| Killed | 251 | 293 |
| Survived | 75 | 280 |
| No tests | 17 | 0 |
| Timeout | 0 | 0 |
| Suspicious | 0 | 0 |
| Mutation score, killed/(killed+survived) | 77.0% | 51.1% |
| Module wall clock, whole run | 6.8 s cold, 5.3 s on a repeat | 77.1 s |
| Per-mutant test time, median | 0.049 s | 0.173 s |
| Per-mutant test time, mean / max | 0.059 s / 0.309 s | 0.507 s / 4.558 s |
| One mutant, end to end | 1.02 s | 2.19 s |

Wall clock is `/usr/bin/time -p` around the whole `mutmut run`, so it includes mutant generation, the one-time stats pass over the test module, and the clean-test check. "One mutant, end to end" is a second `mutmut run <mutant-name>` on cached state, so it includes the tool's own start-up, not just the test call. Mutmut has no unviable verdict, and none appeared; it also reports no skipped mutants.

The mutator set matters as much as the version here: a score is not comparable across either. Mutmut 3.8.1 generates, via libcst: number literals shifted by one; string literals wrapped in `XX` or case-flipped; `True`/`False` and `is`/`in`/`break`/`continue` swaps; assignment values replaced with `None` or `""`; unary operators dropped; call arguments and keyword arguments removed; `lower`/`upper`, `lstrip`/`rstrip`, `find`/`rfind` and `split`/`rsplit` swaps; lambda bodies replaced; operator swaps across boolean, comparison and arithmetic operators; match cases removed; ternaries forced down one branch.

### The commands

The mirror exists because mutmut copies the source into `mutants/` and runs pytest from there, and these test modules resolve the repo root as `Path(__file__).parents[2]`. Inside the mirror that lands on the CLI directory, so the repo-root files the tests read have to be present one level up from `tests/`.

```sh
SCRATCH=$(mktemp -d)
rsync -a cli/ "$SCRATCH/cli/"
rsync -a compose/ "$SCRATCH/compose/"
rsync -a compose/ "$SCRATCH/cli/compose/"     # what test_pins.py reads as the repo root
cp .gitleaks.toml "$SCRATCH/.gitleaks.toml"
cd "$SCRATCH" && python3 cli/scripts/sync_compose_resources.py

uv venv --python 3.13 "$SCRATCH/venv"
uv pip install --python "$SCRATCH/venv/bin/python" \
  "mutmut==3.8.1" pytest click pyyaml cryptography jinja2 requests
```

Temporary `cli/setup.cfg` in the mirror only, rewritten between the two runs (mutmut reads `[tool.mutmut]` from `pyproject.toml` first, then falls back to `setup.cfg`):

```ini
[mutmut]
source_paths = .
only_mutate = cove/pins.py            # cove/update.py for the second run
pytest_add_cli_args_test_selection =
    tests/test_pins.py                # tests/test_update.py for the second run
use_git_change_detection = false
```

```sh
cd "$SCRATCH/cli"
/usr/bin/time -p "$SCRATCH/venv/bin/python" -m mutmut run --max-children 4
"$SCRATCH/venv/bin/python" -m mutmut results
"$SCRATCH/venv/bin/python" -m mutmut show <mutant-name>
/usr/bin/time -p "$SCRATCH/venv/bin/python" -m mutmut run <mutant-name>   # single-mutant timing
```

Test selection is per module on purpose: the unit tier as a whole does not survive the mirror, because 126 of its cases failed or errored on repo-root paths that `cli/` alone does not carry. Mutmut's own per-test selection narrows each mutant to the tests that reach its function, which is why a mutant costs 0.05-0.17 s instead of the 0.37-0.63 s the whole test module takes.

### The first five survivors, `pins.py`

Verdicts are mine; the mutation is quoted from the tool.

| Mutant | Mutation | Verdict | Why |
|-|-|-|-|
| `x__render_simple__mutmut_8` | `[A-Za-z_0-9]` → `[a-za-z_0-9]` | Missing test | No test renders a template through `_render_simple` directly, and every variable name in `compose/` is lowercase, so dropping `A-Z` changes nothing the suite can see. An uppercase name would no longer be substituted. |
| `x__render_simple__mutmut_13` | `variables.get(m.group(1), m.group(0))` → `variables.get(m.group(1), None)` | Missing test | The fallback that leaves an unknown placeholder intact is unpinned. No test renders a template whose variable is absent. |
| `x__render_simple__mutmut_15` | `.get(m.group(1), m.group(0))` → `.get(m.group(1), )` | Missing test | Same rule as above, reached by a different operator: the default argument is removed, so a missing variable yields `None`. |
| `x__render_simple__mutmut_19` | default `m.group(0)` → `m.group(1)` | Missing test | Same gap again: the mutant substitutes the bare name instead of the whole `{{ name }}`, which is observable only when the variable is missing. |
| `x__from_group_vars__mutmut_10` | `key.endswith("_image") and isinstance(value, str)` → `... or ...` | Missing test | Only an `*_image` key holding a non-string value tells the two apart, and no fixture has one. With such a value the mutant would reach `_render_simple` and raise. |

### The first five survivors, `update.py`

All five land in one function, which is itself a result about where the mutator spends its budget.

| Mutant | Mutation | Verdict | Why |
|-|-|-|-|
| `x__repo_url__mutmut_3` | `Path.home() / "Documents" / "code" / "cove"` → `None` | Missing test | No test asserts the path passed to `git -C`. `test_env_override_wins` only asserts the probe is skipped, and the other tests stub `subprocess.run`, so the argument is never inspected. |
| `x__repo_url__mutmut_7` | `"Documents"` → `"XXDocumentsXX"` | Missing test | Same gap: the probe path is unasserted, so any corrupted path survives. |
| `x__repo_url__mutmut_8` | `"Documents"` → `"documents"` | Missing test | Same gap, case variant. |
| `x__repo_url__mutmut_9` | `"Documents"` → `"DOCUMENTS"` | Missing test | Same gap, upper-case variant. |
| `x__repo_url__mutmut_10` | `"code"` → `"XXcodeXX"` | Missing test | Same gap, second path segment. |

None of these are equivalent: a wrong path makes the probe fail in production and `_repo_url` raise. None are dead. The suite simply never looks at which directory is probed.

Because the first five were all one shape, here are five more from elsewhere, chosen to show the other two verdict classes the experiment asks about.

| Mutant | Mutation | Verdict | Why |
|-|-|-|-|
| `x__classifier__mutmut_32` | `ref.rsplit(":", 1)[-1]` → `ref.rsplit(None, 1)[-1]` | Equivalent mutant (dead code) | In `_classifier`, the block guarded by `if ":" in ref and "/" not in ...` returns `"tag"`, and so does the line after it. The block computes `digits` and throws it away, so `last_segment` and every mutation inside the block are unobservable. 23 of the 75 `pins.py` survivors sit in this dead block. |
| `x__convergence_pending__mutmut_6` | `return True` → `return False` where the bundled tree cannot be read | Missing test | The comment says "cannot prove no-impact → converge (fail loud)". `test_wheel_without_compose_reads_as_pending` builds a wheel whose compose tree is empty (`{}`, not `None`), so the branch is never taken and the fail-loud rule is unpinned. |
| `x__do_update__mutmut_42` | `_converge(..., wheel_path=wheel_path)` → `wheel_path=None` | Missing test | This is the issue #80 regression itself. The test's deployed fixture is built from the same bundled tree the current process reads, so both sides of the comparison agree and the test cannot tell the two calls apart. |
| `x__cove_bin__mutmut_12` | `is_absolute() and is_file() and os.access(...)` → `... and is_file() or os.access(...)` | Missing test | The suite covers "resolvable binary" and "nothing resolvable". It has no case for an absolute path that exists but is not executable, which is the only input that separates `and` from `or` here. |
| `x__install_wheel__mutmut_33` | `check=True` → `check=False` on `git worktree add` | Missing test | Every test stubs `subprocess.run` and accepts `**kwargs` without inspecting them, so the fail-loud `check=True` discipline the module documents is unasserted. |

### What the survivors look like

Counting the patch text of all 280 `update.py` survivors by pattern: 64 wrap a string in `XX`, 70 change only letter case, 61 replace an expression with `None`, and 85 are structural. The first three groups are 70% of the survivors and they are all real behaviour changes, not equivalents, but they land in log lines, error text and `subprocess` plumbing. "Fix every survivor" is not a useful response to `"docker ps failed"` becoming `"XXdocker ps failedXX"`.

In `pins.py`, 30 of the 75 survivors are in `_classifier`, and 23 of those are the dead block above. That is 31% of that module's survivors that no test could ever kill, and it is a code defect the mutation run found for free.

The 17 "no tests" mutants are all in `main()`. That verdict is wrong in a useful way: `test_pins_module_json_output` does cover `main()`, by running `python -m cove.pins` in a subprocess, which mutmut's in-process test tracing cannot see. "No tests" here means "no test in this process reached it", not "untested".

### What this changes in the argument

The arithmetic in this document charges one full suite run (84 s) per mutant, and the tool does not: with per-test selection the measured cost is 0.05-0.5 s per mutant, which is the difference between a nightly job and a check that fits inside a pull request.

This also corrects the cost paragraph in the addendum above, which prices 1,000 mutants at 15 to 24 CPU-hours from a 55-85 s full-suite run each. Measured per-test selection puts a 1,000-mutant run on `update.py`-shaped code at about two minutes of wall clock on four workers. The three-tier design above still stands and gains headroom; what does not stand is the per-mutant cost it was derived from.

That projection is inferred, not observed: at the `update.py` throughput (7.8 mutants/s with four workers), 3,000 mutants would take about six and a half minutes, and the whole-repo figure in the arithmetic section assumed a full suite run per mutant, which no tool here does by default.

The other correction is to the guess about equivalence. The document speculated a five percent equivalent rate. This run measured 31% of `pins.py`'s survivors as unkillable by construction, in one dead branch, before counting any judgement calls. That does not make the score useless; it makes the survivor count per module, not the percentage, the number a developer can act on, which is the design the measurement section already proposed.

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
