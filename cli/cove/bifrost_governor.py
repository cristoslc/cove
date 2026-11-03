"""Windowed regime governor for the Bifrost standard tiers.

Bifrost v2.3.2 has no latency-aware routing primitive: a routing rule is a
static CEL match, and `ttft_timeout_ms` is a per-request cutoff. The windowed
regime rule therefore lives outside the gateway as a small controller:

  escalate the standard tier while the median first-token time of the last N
  requests exceeds a threshold, with hard caps on episodes per hour and per
  week, and restore the moment the median falls back.

The signal is Bifrost's own `bifrost_stream_first_token_latency_seconds`
histogram (streaming TTFT), scraped from `/metrics` with the dashboard Basic
credentials. The histogram is cumulative, so each pass stores a bucket
snapshot and keeps a short ring of deltas; the median is read from the sum of
the most recent deltas covering at least N samples.

This module is pure decision logic plus injected I/O so it can be tested
without a gateway. `cove bifrost governor` wires it to the live admin API.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

METRIC = "bifrost_stream_first_token_latency_seconds_bucket"
# The two standard-tier aliases share one chain and one wire model, so they
# are governed as a single group. text:light is excluded: its fallback is a
# different model and it carried 7 requests in the measured week.
GOVERNED_RULES = ("rr-vision-standard", "rr-text-standard")
FALLBACK_TARGET = {
    "provider": "ollama-cloud",
    "model": "deepseek-v4.1-flash",
    "weight": 1.0,
    # Keep the merged per-request net on the escalated target too.
    "ttft_timeout_ms": 25000,
}
ESCALATION_FALLBACKS = ["syn-infinite-backstop/infinite:small:vision"]

DEFAULTS = {
    "threshold_ms": 6000,
    "exit_ms": 4000,
    "samples": 20,
    "window_minutes": 15,
    "max_per_hour": 3,
    "max_per_week": 8,
    "max_dwell_min": 15,
    "cooldown_min": 10,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _le(value: str) -> float:
    return float("inf") if value in ("+Inf", "Inf", "inf") else float(value)


def parse_ttft_buckets(text: str) -> dict[str, dict[float, int]]:
    """Parse the cumulative TTFT histogram into {rule_id: {le: count}}."""
    out: dict[str, dict[float, int]] = {}
    for line in text.splitlines():
        if not line.startswith(METRIC + "{"):
            continue
        try:
            labels, raw = line.rsplit("}", 1)
            labels = labels[len(METRIC) + 1:]
            value = float(raw.strip())
        except ValueError:
            continue
        rule = le = None
        for part in labels.split(","):
            key, _, val = part.partition("=")
            val = val.strip().strip('"')
            if key == "routing_rule_id":
                rule = val
            elif key == "le":
                le = val
        if rule and le is not None:
            out.setdefault(rule, {})[_le(le)] = int(value)
    return out


def pooled_buckets(
    parsed: dict[str, dict[float, int]],
    rules: tuple[str, ...] = GOVERNED_RULES,
) -> dict[float, int]:
    pooled: dict[float, int] = {}
    for rule in rules:
        for le, count in parsed.get(rule, {}).items():
            pooled[le] = pooled.get(le, 0) + count
    return pooled


def median_ms(buckets: dict[float, int]) -> float | None:
    """Median from a cumulative bucket map, in milliseconds."""
    if not buckets:
        return None
    total = buckets.get(float("inf"))
    if total is None:
        total = max(buckets.values())
    if total <= 0:
        return None
    ordered = sorted(buckets.items())
    half = total / 2.0
    previous = 0
    previous_le = 0.0
    for le, count in ordered:
        if count >= half:
            if le == float("inf"):
                return previous_le * 1000.0
            # Linear interpolation inside the bucket keeps the estimate from
            # snapping to the upper bound on every sample.
            span = count - previous
            frac = 0.5 if span <= 0 else (half - previous) / span
            return (previous_le + (le - previous_le) * frac) * 1000.0
        previous = count
        previous_le = le
    return ordered[-1][0] * 1000.0


def _delta(current: dict[float, int], previous: dict[float, int]) -> dict[float, int] | None:
    """Cumulative-counter delta. None means the counter reset (restart)."""
    out: dict[float, int] = {}
    for le, count in current.items():
        prev = previous.get(le, 0)
        if count < prev:
            return None
        out[le] = count - prev
    return out


def _sum_buckets(items: list[dict[float, int]]) -> dict[float, int]:
    out: dict[float, int] = {}
    for item in items:
        for le, count in item.items():
            out[le] = out.get(le, 0) + count
    return out


def _samples(buckets: dict[float, int]) -> int:
    if float("inf") in buckets:
        return buckets[float("inf")]
    return max(buckets.values(), default=0)


def decide(
    *,
    now: datetime,
    median: float | None,
    samples: int,
    state: dict,
    threshold_ms: int,
    exit_ms: int,
    min_samples: int,
    max_per_hour: int,
    max_per_week: int,
    max_dwell_min: int,
    cooldown_min: int,
) -> dict:
    """Return {"action", "reason"}; action is escalate, restore, or hold."""
    active = state.get("active")
    if median is None or samples < min_samples:
        if active:
            # No signal is not a reason to stay escalated; restore on stale
            # data at the dwell limit only.
            started = _parse_ts(active["started"])
            if now - started >= timedelta(minutes=max_dwell_min):
                return {"action": "restore", "reason": "stale signal, dwell limit"}
        return {"action": "hold", "reason": f"insufficient samples ({samples}/{min_samples})"}

    if active:
        started = _parse_ts(active["started"])
        if now - started >= timedelta(minutes=max_dwell_min):
            return {"action": "restore", "reason": "dwell limit"}
        if median <= exit_ms:
            return {"action": "restore", "reason": f"median {median:.0f}ms <= exit {exit_ms}ms"}
        return {"action": "hold", "reason": f"active, median {median:.0f}ms"}

    if median < threshold_ms:
        return {"action": "hold", "reason": f"median {median:.0f}ms < threshold {threshold_ms}ms"}

    episodes = state.get("episodes", [])
    starts = [_parse_ts(e["start"]) for e in episodes]
    if active:
        starts.append(_parse_ts(active["started"]))
    hour_ago = now - timedelta(hours=1)
    week_ago = now - timedelta(days=7)
    if sum(1 for s in starts if s >= hour_ago) >= max_per_hour:
        return {"action": "hold", "reason": f"hourly cap ({max_per_hour}) reached"}
    if sum(1 for s in starts if s >= week_ago) >= max_per_week:
        return {"action": "hold", "reason": f"weekly cap ({max_per_week}) reached"}

    ends = [_parse_ts(e["end"]) for e in episodes if e.get("end")]
    if ends and now - max(ends) < timedelta(minutes=cooldown_min):
        return {"action": "hold", "reason": f"cooldown ({cooldown_min}m) not elapsed"}
    return {"action": "escalate", "reason": f"median {median:.0f}ms >= threshold {threshold_ms}ms"}


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"governor state at {path} is unreadable: {exc}")


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".governor-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Governor:
    """One evaluation pass with injected I/O."""

    def __init__(self, *, metrics_fn, rules_fn, update_fn, state_path: Path,
                 options: dict | None = None, now_fn=_now):
        self.metrics_fn = metrics_fn
        self.rules_fn = rules_fn
        self.update_fn = update_fn
        self.state_path = Path(state_path)
        self.opt = {**DEFAULTS, **(options or {})}
        self.now_fn = now_fn

    def pass_once(self, apply: bool) -> dict:
        now = self.now_fn()
        state = load_state(self.state_path)
        parsed = parse_ttft_buckets(self.metrics_fn())
        current = pooled_buckets(parsed)
        last = state.get("last")
        reset = False
        delta = None
        if last:
            delta = _delta(current, {_le(k) if isinstance(k, str) else k: v
                                     for k, v in last.get("buckets", {}).items()})
            reset = delta is None
        if delta is None:
            delta = {le: 0 for le in current}

        history = state.get("history", [])
        if delta and any(delta.values()):
            history.append({"ts": _iso(now), "buckets": {str(k): v for k, v in delta.items()}})
        cutoff = now - timedelta(minutes=self.opt["window_minutes"])
        history = [h for h in history if _parse_ts(h["ts"]) >= cutoff]
        window = _sum_buckets([{_le(k): v for k, v in h["buckets"].items()} for h in history])
        median = median_ms(window)
        samples = _samples(window)

        verdict = decide(
            now=now, median=median, samples=samples, state=state,
            threshold_ms=self.opt["threshold_ms"], exit_ms=self.opt["exit_ms"],
            min_samples=self.opt["samples"], max_per_hour=self.opt["max_per_hour"],
            max_per_week=self.opt["max_per_week"],
            max_dwell_min=self.opt["max_dwell_min"],
            cooldown_min=self.opt["cooldown_min"],
        )

        result = {
            "action": verdict["action"],
            "reason": verdict["reason"],
            "median_ms": median,
            "samples": samples,
            "counter_reset": reset,
            "applied": False,
        }
        if apply and verdict["action"] in ("escalate", "restore"):
            result.update(self._apply(now, state, verdict["action"]))
            result["applied"] = True

        if apply:
            state["last"] = {"ts": _iso(now), "buckets": {str(k): v for k, v in current.items()}}
            state["history"] = history
            if verdict["action"] == "escalate":
                state["active"] = state.get("active") or {
                    "started": _iso(now),
                    "originals": result.get("originals", {}),
                }
            elif verdict["action"] == "restore":
                active = state.get("active") or {}
                state.setdefault("episodes", []).append({
                    "start": active.get("started", _iso(now)),
                    "end": _iso(now),
                    "median_ms": median,
                    "samples": samples,
                })
                state["active"] = None
            save_state(self.state_path, state)
        return result

    def _apply(self, now: datetime, state: dict, action: str) -> dict:
        rules = {r["id"]: r for r in self.rules_fn()}
        if action == "escalate":
            originals = {}
            for rule_id in GOVERNED_RULES:
                rule = rules.get(rule_id)
                if not rule:
                    raise RuntimeError(f"governed rule {rule_id} is missing from the gateway")
                originals[rule_id] = {
                    "targets": rule.get("targets", []),
                    "fallbacks": rule.get("fallbacks", []),
                }
            # Only mutate once every original is captured, so a missing rule
            # cannot leave a half-swapped tier behind.
            for rule_id in GOVERNED_RULES:
                self.update_fn(rule_id, {
                    "targets": [dict(FALLBACK_TARGET)],
                    "fallbacks": list(ESCALATION_FALLBACKS),
                })
            return {"originals": originals}

        originals = (state.get("active") or {}).get("originals", {})
        for rule_id, original in originals.items():
            self.update_fn(rule_id, original)
        return {"originals": originals}
