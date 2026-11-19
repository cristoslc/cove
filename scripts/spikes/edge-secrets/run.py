#!/usr/bin/env python3
"""Spike: can the repo's Gitleaks rules run as an edge secrets check?

Runs every fixture in ``corpus/`` through ``gitleaks stdin`` with the repo's
own ``.gitleaks.toml``, twice, and reports:

* detection on the ``pos-*`` fixtures (a real secret shape must fire);
* false positives on the ``neg-*`` fixtures (ordinary prose and code must not);
* wall time per scan, which decides whether the check can sit on a request path.

Fixtures carry fake values in real shapes. Nothing here is a live secret.

Usage:
    python3 run.py [--gitleaks PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE.parent.parent.parent / ".gitleaks.toml"


def find_gitleaks(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("gitleaks")
    if found:
        return found
    raise SystemExit("gitleaks not found; pass --gitleaks or put it on PATH")


def scan(gitleaks: str, fixture: Path) -> tuple[bool, list[str], float]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        report = Path(handle.name)
    started = time.monotonic()
    subprocess.run(
        [
            gitleaks,
            "stdin",
            "--config",
            str(CONFIG),
            "--redact",
            "--exit-code",
            "0",
            "--report-format",
            "json",
            "--report-path",
            str(report),
        ],
        stdin=fixture.open("rb"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    elapsed = (time.monotonic() - started) * 1000
    try:
        findings = json.loads(report.read_text() or "[]")
    except ValueError:
        findings = []
    report.unlink(missing_ok=True)
    rules = sorted({finding.get("RuleID", "?") for finding in findings})
    return bool(findings), rules, elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gitleaks")
    parser.add_argument("--config", help="config to scan with (default: the repo .gitleaks.toml)")
    parser.add_argument("--runs", type=int, default=2, help="runs per fixture; the best time is reported")
    args = parser.parse_args()
    gitleaks = find_gitleaks(args.gitleaks)
    global CONFIG
    if args.config:
        CONFIG = Path(args.config).resolve()
    if not CONFIG.is_file():
        raise SystemExit(f"missing config: {CONFIG}")

    fixtures = sorted((HERE / "corpus").glob("*.txt"))
    if not fixtures:
        raise SystemExit("no fixtures in corpus/")

    true_pos = false_neg = false_pos = true_neg = 0
    times: list[float] = []
    print(f"{'fixture':32} {'expected':9} {'fired':6} {'rules':40} {'ms':>7}")
    for fixture in fixtures:
        expected = fixture.name.startswith("pos-")
        best = float("inf")
        fired = False
        rules: list[str] = []
        for _ in range(max(1, args.runs)):
            fired, rules, elapsed = scan(gitleaks, fixture)
            best = min(best, elapsed)
        times.append(best)
        verdict = "PASS" if fired == expected else "FAIL"
        if expected and fired:
            true_pos += 1
        elif expected and not fired:
            false_neg += 1
        elif not expected and fired:
            false_pos += 1
        else:
            true_neg += 1
        print(
            f"{fixture.name:32} {'secret' if expected else 'ordinary':9} "
            f"{str(fired):6} {','.join(rules)[:40]:40} {best:7.1f} {verdict}"
        )

    print()
    print(f"true positives: {true_pos}   false negatives: {false_neg}")
    print(f"true negatives: {true_neg}   false positives: {false_pos}")
    if times:
        times.sort()
        print(
            f"per-scan ms: min {times[0]:.0f}  median {times[len(times)//2]:.0f}  max {times[-1]:.0f}"
        )
    return 0 if false_neg == 0 and false_pos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
