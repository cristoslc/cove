"""Tests for the Bifrost windowed regime governor.

The governor is pure decision logic with injected I/O: every test here runs
without a gateway, and the rules/config assertions prove the shipped ladder is
untouched.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cove import bifrost_governor as gov
from cove.bifrost_governor import Governor, decide, median_ms, parse_ttft_buckets


def metrics_text(counts: dict[str, dict[str, int]]) -> str:
    lines = []
    for rule, buckets in counts.items():
        for le, n in buckets.items():
            lines.append(
                f'bifrost_stream_first_token_latency_seconds_bucket'
                f'{{routing_rule_id="{rule}",provider="syn-subscription",'
                f'model="m",le="{le}"}} {n}'
            )
    return "\n".join(lines) + "\n"


BUCKETS = ("2.5", "5", "10", "18", "20", "25", "+Inf")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class FakeGateway:
    def __init__(self):
        self.obs = {}          # rule -> first-token seconds, one per request
        self.updates = []
        self.rules = {
            "rr-vision-standard": {
                "id": "rr-vision-standard",
                "targets": [{"provider": "syn-subscription",
                             "model": "hf:deepseek-ai/DeepSeek-V4.1-Flash",
                             "weight": 1.0, "ttft_timeout_ms": 25000}],
                "fallbacks": ["ollama-cloud/deepseek-v4.1-flash",
                              "syn-infinite-backstop/infinite:small:vision"],
            },
            "rr-text-standard": {
                "id": "rr-text-standard",
                "targets": [{"provider": "syn-subscription",
                             "model": "hf:deepseek-ai/DeepSeek-V4.1-Flash",
                             "weight": 1.0, "ttft_timeout_ms": 25000}],
                "fallbacks": ["ollama-cloud/deepseek-v4.1-flash",
                              "syn-infinite-backstop/infinite:small:vision"],
            },
        }

    def add(self, seconds, n=1, rule="rr-vision-standard"):
        self.obs.setdefault(rule, []).extend([seconds] * n)

    def metrics(self):
        counts = {}
        for rule, values in self.obs.items():
            counts[rule] = {
                le: sum(1 for v in values
                        if v <= (float("inf") if le == "+Inf" else float(le)))
                for le in BUCKETS
            }
        return metrics_text(counts)

    def list_rules(self):
        return list(self.rules.values())

    def update(self, rule_id, body):
        self.updates.append((rule_id, body))


def make(clock, gateway, state, **opts):
    return Governor(metrics_fn=gateway.metrics, rules_fn=gateway.list_rules,
                    update_fn=gateway.update, state_path=state,
                    options=opts, now_fn=clock)


def test_parse_and_median():
    text = metrics_text({"rr-vision-standard": {"5": 0, "10": 20, "+Inf": 20}})
    parsed = parse_ttft_buckets(text)
    assert parsed["rr-vision-standard"][10.0] == 20
    assert parsed["rr-vision-standard"][float("inf")] == 20
    # 20 samples, half at position 10, inside (5, 10]: 5 + 0.5 * 5 = 7.5s
    assert median_ms(parsed["rr-vision-standard"]) == pytest.approx(7500)


def test_parse_ignores_other_metrics():
    text = (
        'bifrost_upstream_latency_seconds_bucket{routing_rule_id="x",le="1"} 5\n'
        'bifrost_stream_first_token_latency_seconds_bucket{routing_rule_id="x",le="1"} 5\n'
    )
    assert set(parse_ttft_buckets(text)) == {"x"}


def test_decide_escalates_and_restores():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    base = dict(threshold_ms=6000, exit_ms=4000, min_samples=20,
                low_rate_samples=8, low_rate_span_min=10,
                max_per_hour=3, max_per_week=8, max_dwell_min=15, cooldown_min=10)
    state = {}
    assert decide(now=now, median=7500, samples=20, span_min=14,
                  state=state, **base)["action"] == "escalate"
    state = {"active": {"started": gov._iso(now)}}
    assert decide(now=now, median=1500, samples=20, span_min=14,
                  state=state, **base)["action"] == "restore"
    assert decide(now=now, median=7500, samples=20, span_min=14,
                  state=state, **base)["action"] == "hold"
    later = now + timedelta(minutes=16)
    assert decide(now=later, median=7500, samples=20, span_min=14,
                  state=state, **base)["action"] == "restore"


def test_decide_caps_and_cooldown():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    base = dict(threshold_ms=6000, exit_ms=4000, min_samples=20,
                low_rate_samples=8, low_rate_span_min=10,
                max_per_hour=2, max_per_week=8, max_dwell_min=15, cooldown_min=10)
    state = {"episodes": [
        {"start": gov._iso(now - timedelta(minutes=30)),
         "end": gov._iso(now - timedelta(minutes=10))},
        {"start": gov._iso(now - timedelta(minutes=20)),
         "end": gov._iso(now - timedelta(minutes=5))},
    ]}
    assert "hourly cap" in decide(now=now, median=7500, samples=20, span_min=14, state=state, **base)["reason"]
    state["episodes"] = [{"start": gov._iso(now - timedelta(minutes=30)),
                          "end": gov._iso(now - timedelta(minutes=5))}]
    assert "cooldown" in decide(now=now, median=7500, samples=20, span_min=14, state=state, **base)["reason"]
    state["episodes"] = [{"start": gov._iso(now - timedelta(days=1)),
                          "end": gov._iso(now - timedelta(days=1, minutes=-1))}]
    assert decide(now=now, median=7500, samples=20, span_min=14, state=state, **base)["action"] == "escalate"


def test_insufficient_samples_holds():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    verdict = decide(now=now, median=None, samples=3, span_min=1, state={},
                     threshold_ms=6000, exit_ms=4000, min_samples=20,
                     low_rate_samples=8, low_rate_span_min=10,
                     max_per_hour=3, max_per_week=8, max_dwell_min=15,
                     cooldown_min=10)
    assert verdict["action"] == "hold"
    assert "insufficient" in verdict["reason"]


def test_dry_run_does_not_mutate_or_write(tmp_path):
    clock, gateway = Clock(), FakeGateway()
    state = tmp_path / "state.json"
    run = make(clock, gateway, state)
    assert run.pass_once(apply=True)["action"] == "hold"  # baseline pass
    before = state.read_bytes()
    gateway.add(19.0, n=20)
    clock.advance(minutes=1)
    result = run.pass_once(apply=False)
    assert result["action"] == "escalate"
    assert result["applied"] is False
    assert gateway.updates == []
    assert state.read_bytes() == before


def test_apply_escalates_then_restores(tmp_path):
    clock, gateway = Clock(), FakeGateway()
    state = tmp_path / "state.json"
    run = make(clock, gateway, state)

    run.pass_once(apply=True)  # baseline
    gateway.add(19.0, n=20)
    clock.advance(minutes=1)
    result = run.pass_once(apply=True)
    assert result["action"] == "escalate" and result["applied"] is True
    assert len(gateway.updates) == 2
    for rule_id, body in gateway.updates:
        assert body["targets"][0]["provider"] == "ollama-cloud"
        assert body["targets"][0]["ttft_timeout_ms"] == 25000
        assert body["fallbacks"] == ["syn-infinite-backstop/infinite:small:vision"]
    saved = json.loads(state.read_text())
    assert saved["active"]["started"]
    assert set(saved["active"]["originals"]) == {"rr-vision-standard", "rr-text-standard"}

    gateway.updates.clear()
    clock.advance(minutes=5)
    # Slow deltas time out only after the 15-minute window; add fast deltas on
    # top so the pooled median falls below the exit threshold.
    for rule in ("rr-vision-standard", "rr-text-standard"):
        gateway.add(1.5, n=20, rule=rule)
    result = run.pass_once(apply=True)
    assert result["action"] == "restore"
    assert len(gateway.updates) == 2
    for rule_id, body in gateway.updates:
        assert body["targets"][0]["provider"] == "syn-subscription"
        assert body["fallbacks"][0] == "ollama-cloud/deepseek-v4.1-flash"
    saved = json.loads(state.read_text())
    assert saved["active"] is None
    assert len(saved["episodes"]) == 1


def test_counter_reset_rebaselines(tmp_path):
    clock, gateway = Clock(), FakeGateway()
    state = tmp_path / "state.json"
    run = make(clock, gateway, state)
    gateway.add(19.0, n=20)
    run.pass_once(apply=True)
    gateway.obs = {"rr-vision-standard": [19.0] * 5}  # gateway restarted
    clock.advance(minutes=1)
    result = run.pass_once(apply=True)
    assert result["counter_reset"] is True
    assert result["samples"] == 0


def test_shipped_config_keeps_the_25s_net():
    """The governor flips targets at runtime; the committed ladder and the
    per-request net must be untouched by this change."""
    cfg = json.loads((Path(__file__).resolve().parents[2]
                      / "compose/bifrost/config.json").read_text())
    rules = {r["cel_expression"].split("'")[1]: r
             for r in cfg["governance"]["routing_rules"]}
    for tier in ("vision:standard", "text:standard", "text:light"):
        assert rules[tier]["targets"][0]["ttft_timeout_ms"] == 25000
    assert rules["vision:standard"]["targets"][0]["provider"] == "syn-subscription"


def test_low_rate_regime_escalates_within_fifteen_minutes(tmp_path):
    """The worst measured regime ran 95 minutes at a 19s median with about 37
    requests an hour, so a 15-minute window held nine samples and the
    20-sample floor never cleared. The low-rate path must reach it inside the
    first window instead of never."""
    clock, gateway = Clock(), FakeGateway()
    run = make(clock, gateway, tmp_path / "state.json")

    run.pass_once(apply=True)              # baseline pass
    started = clock.t
    next_sample = started + timedelta(seconds=97)   # 37 requests/hour
    escalated = None
    result = None
    for _ in range(20):                    # one pass per minute
        clock.advance(minutes=1)
        while clock.t >= next_sample:
            gateway.add(19.0)              # 19-second first token
            next_sample += timedelta(seconds=97)
        result = run.pass_once(apply=True)
        if result["action"] == "escalate":
            escalated = clock.t
            break

    assert escalated is not None, "a 19s median at 37 requests/hour never escalated"
    assert escalated - started <= timedelta(minutes=15)
    assert result["applied"] is True
    assert "low-rate path" in result["reason"]
    assert result["samples"] < 20          # below the ordinary floor
    assert result["span_min"] >= 10


def test_low_rate_path_cannot_fire_on_a_burst_or_a_mediocre_tail(tmp_path):
    """Eight samples only stand in for a regime when they span the window and
    their median is bad. A burst must not qualify, and a quiet stretch of
    ordinary first-token times must never rotate the tier."""
    # (a) eight 19s samples packed into two minutes
    clock, gateway = Clock(), FakeGateway()
    run = make(clock, gateway, tmp_path / "burst.json")
    run.pass_once(apply=True)
    for _ in range(8):
        clock.advance(seconds=15)
        gateway.add(19.0)
        result = run.pass_once(apply=True)
        assert result["action"] == "hold"
    for _ in range(12):                    # the burst ages inside the window
        clock.advance(minutes=1)
        result = run.pass_once(apply=True)
        assert result["action"] == "hold"
    assert "insufficient evidence" in result["reason"]
    assert gateway.updates == []

    # (b) eight samples spread across the window, but only 3s each
    clock, gateway = Clock(), FakeGateway()
    run = make(clock, gateway, tmp_path / "quiet.json")
    run.pass_once(apply=True)
    for _ in range(8):
        clock.advance(seconds=105)         # spans 12 minutes
        gateway.add(3.0)
        result = run.pass_once(apply=True)
        assert result["action"] == "hold"
    assert result["samples"] >= 8
    assert result["span_min"] >= 10
    assert "threshold" in result["reason"]
    assert gateway.updates == []
