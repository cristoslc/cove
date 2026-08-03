# `cove litellm up` broken on Docker Compose v5 (2026-08-03)

Discovered while investigating the LiteLLM container's idle memory footprint and
restarting the service.

## Symptom

`cove litellm up` fails with:

```
subprocess.CalledProcessError: Command '['docker', 'compose', ...,
'up', '-d', '--profile', 'litellm']' returned non-zero exit status 1.
```

and `docker compose up --profile litellm` reports:

```
unknown flag: --profile
```

`cove litellm down` and `cove litellm status` are unaffected — only `up`
uses the `--profile` flag.

## Likely cause

Docker Compose v5.3.1 (bundled with Docker 29.6.2) removed the singular
`--profile` flag from `docker compose up`. Profiles are now activated via the
`COMPOSE_PROFILES` environment variable. The CLI still hardcodes `--profile
litellm` in `cli/cove/litellm.py:32`.

Working invocation:

```
COMPOSE_PROFILES=litellm docker compose up -d
```

## Reproduce

```
uv run --directory cli cove litellm up
```

or directly:

```
cd compose && docker compose up -d --profile litellm
```

## Impact

`cove litellm up` cannot start LiteLLM/Headroom until fixed. Workaround:
`cd compose && COMPOSE_PROFILES=litellm docker compose up -d`.

## Tests affected

`cli/tests/test_litellm.py::TestLitellmCommands::test_litellm_up_uses_profile_flag`
asserts the source contains `--profile` and `litellm`. The test does not
actually run compose, so it passes — but it asserts a now-broken invocation.
The fix must update both the CLI and this test.
