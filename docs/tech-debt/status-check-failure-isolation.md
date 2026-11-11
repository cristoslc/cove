# `cove status` aborts the whole report when one check raises

**Date:** 2026-11-11 (found while fixing the Linux `dscacheutil` crash)
**Severity:** medium (diagnostic command unusable; every other check's result is lost)
**Component:** `cli/cove/status.py` — `check_all()`

## Problem

`check_all()` appends each check result in a straight line:

```python
results.extend(_check_containers())
results.append(_check_nginx_ingress())
...
results.append(_check_dns())
```

Nothing isolates a check that raises. The Linux `_check_dns` crash (`FileNotFoundError: dscacheutil`) showed the consequence: the DNS row's exception escaped `check_all()` and `cli.status()`, so `cove status` printed a traceback and zero rows — including the container, nginx, Forgejo, and Vault results that had already been computed or would have been fine.

This sashay fixed the crashing check itself. It did not add a global guard, because wrapping every check in a broad `except Exception` would swallow programming errors and conflict with the project's fail-loud rule.

## Desired shape

Each check should be able to fail independently while still reporting loudly. A guard that catches an exception and renders it as its own `CheckResult(ok=False, detail=f"{name} check raised {type(exc).__name__}: {exc}")` would keep the report alive without hiding the error. The awkward part is naming: `_check_containers()` returns a list while the other checks return one result, so the guard needs a per-call name rather than reflection.

## Acceptance sketch

- A test patches one check to raise and asserts `cove status` still prints the other rows and exits non-zero.
- The failing row's detail contains the exception type and message.
- No bare `except`; the guard catches `Exception` with a comment explaining why broadness is deliberate here.
