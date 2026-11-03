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


def slow_counts(n=20, rule="rr-vision-standard"):
    return {rule: {"5": 0, "10": n, "+Inf": n}}


def fast_counts(n=20, rule="rr-vision-standard"):
    return {rule: {"2.5": n, "5": n, "10": n, "+Inf": n}}


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class FakeGateway:
    def __init__(self):
        self.counts = {}
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

    def metrics(self):
        return metrics_text(self.counts)

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
                max_per_hour=3, max_per_week=8, max_dwell_min=15, cooldown_min=10)
    state = {}
    assert decide(now=now, median=7500, samples=20, state=state, **base)["action"] == "escalate"
    state = {"active": {"started": gov._iso(now)}}
    assert decide(now=now, median=1500, samples=20, state=state, **base)["action"] == "restore"
    assert decide(now=now, median=7500, samples=20, state=state, **base)["action"] == "hold"
    later = now + timedelta(minutes=16)
    assert decide(now=later, median=7500, samples=20, state=state, **base)["action"] == "restore"


def test_decide_caps_and_cooldown():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    base = dict(threshold_ms=6000, exit_ms=4000, min_samples=20,
                max_per_hour=2, max_per_week=8, max_dwell_min=15, cooldown_min=10)
    state = {"episodes": [
        {"start": gov._iso(now - timedelta(minutes=30)),
         "end": gov._iso(now - timedelta(minutes=10))},
        {"start": gov._iso(now - timedelta(minutes=20)),
         "end": gov._iso(now - timedelta(minutes=5))},
    ]}
    assert "hourly cap" in decide(now=now, median=7500, samples=20, state=state, **base)["reason"]
    state["episodes"] = [{"start": gov._iso(now - timedelta(minutes=30)),
                          "end": gov._iso(now - timedelta(minutes=5))}]
    assert "cooldown" in decide(now=now, median=7500, samples=20, state=state, **base)["reason"]
    state["episodes"] = [{"start": gov._iso(now - timedelta(days=1)),
                          "end": gov._iso(now - timedelta(days=1, minutes=-1))}]
    assert decide(now=now, median=7500, samples=20, state=state, **base)["action"] == "escalate"


def test_insufficient_samples_holds():
    now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
    verdict = decide(now=now, median=None, samples=3, state={},
                     threshold_ms=6000, exit_ms=4000, min_samples=20,
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
    gateway.counts = slow_counts()
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
    gateway.counts = slow_counts()
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
    gateway.counts = {"rr-vision-standard": {"5": 20, "10": 20, "+Inf": 20},
                      "rr-text-standard": {"5": 0, "10": 20, "+Inf": 20}}
    clock.advance(minutes=5)
    # Slow deltas time out only after the 15-minute window; add fast deltas on
    # top so the pooled median falls below the exit threshold.
    gateway.counts = {
        "rr-vision-standard": {"2.5": 20, "5": 20, "10": 40, "+Inf": 40},
        "rr-text-standard": {"2.5": 20, "5": 20, "10": 40, "+Inf": 40},
    }
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
    gateway.counts = slow_counts(20)
    run.pass_once(apply=True)
    gateway.counts = slow_counts(5)  # gateway restarted, counters reset
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
