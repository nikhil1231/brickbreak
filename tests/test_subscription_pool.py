"""Tests for Stage Z subscription pool and provider routing."""
from __future__ import annotations

import pytest

from src.providers import (
    AsymmetricRoleError,
    MockProviderAdapter,
    NoFallbackError,
    ProviderRole,
    ProviderType,
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    SubscriptionLane,
    SubscriptionPool,
    route_council_call,
    validate_asymmetric_assignment,
)


def test_subscription_pool_dispatch_and_token_accounting():
    lane_mock = SubscriptionLane("mock_lane", ProviderType.MOCK, MockProviderAdapter(ProviderType.MOCK, "Generated answer"))
    pool = SubscriptionPool(lanes=[lane_mock])

    resp = pool.dispatch(ProviderType.MOCK, prompt="Test prompt", system_prompt="Sys")
    assert resp == "Generated answer"
    assert lane_mock.usage.total_calls == 1
    assert lane_mock.usage.input_tokens > 0
    assert lane_mock.usage.output_tokens > 0


def test_no_silent_fallback_on_unavailable_provider():
    class UnavailAdapter(MockProviderAdapter):
        def is_available(self) -> bool:
            return False

    lane = SubscriptionLane("dead_lane", ProviderType.CLAUDE, UnavailAdapter(ProviderType.CLAUDE))
    pool = SubscriptionPool(lanes=[lane])

    with pytest.raises(NoFallbackError, match="Silent fallback to another provider is prohibited"):
        pool.dispatch(ProviderType.CLAUDE, prompt="prompt", allow_fallback=False)


def test_asymmetric_assignment_validation():
    # Same provider for propose and review is disallowed
    with pytest.raises(AsymmetricRoleError, match="propose or approve a dossier, not both"):
        validate_asymmetric_assignment(ProviderType.CLAUDE, ProviderType.CLAUDE)

    # Different providers allowed
    validate_asymmetric_assignment(ProviderType.CLAUDE, ProviderType.CODEX)
    validate_asymmetric_assignment(ProviderType.CLAUDE, ProviderType.ANTIGRAVITY)


def test_route_council_call():
    lane_claude = SubscriptionLane("c_lane", ProviderType.CLAUDE, MockProviderAdapter(ProviderType.CLAUDE, "Scout idea"))
    lane_codex = SubscriptionLane("x_lane", ProviderType.CODEX, MockProviderAdapter(ProviderType.CODEX, "Critic response"))
    pool = SubscriptionPool(lanes=[lane_claude, lane_codex])

    # Scout call routes to Claude
    resp1, p1 = route_council_call(pool, role=ProviderRole.SCOUT, prompt="Find alpha")
    assert p1 == ProviderType.CLAUDE
    assert resp1 == "Scout idea"

    # Critic call routes to Codex (distinct from Claude proposer)
    resp2, p2 = route_council_call(pool, role=ProviderRole.CRITIC, prompt="Critique", proposer_provider=ProviderType.CLAUDE)
    assert p2 == ProviderType.CODEX
    assert resp2 == "Critic response"

    # A Codex proposal is reviewed by available Claude, not the disabled
    # placeholder Google lane.
    resp3, p3 = route_council_call(
        pool, role=ProviderRole.CRITIC, prompt="Critique",
        proposer_provider=ProviderType.CODEX)
    assert p3 == ProviderType.CLAUDE
    assert resp3 == "Scout idea"


def test_route_council_call_forwards_selected_model():
    seen = {}

    class RecordingAdapter(MockProviderAdapter):
        def generate(self, prompt, system_prompt="", model=""):
            seen["model"] = model
            return "answer"

    pool = SubscriptionPool(lanes=[SubscriptionLane(
        "x_lane", ProviderType.CODEX,
        RecordingAdapter(ProviderType.CODEX, "answer"),
    )])

    route_council_call(
        pool, role=ProviderRole.SCOUT, prompt="Find alpha",
        preferred_provider=ProviderType.CODEX, model="gpt-5.6-sol")

    assert seen["model"] == "gpt-5.6-sol"


@pytest.mark.parametrize(
    ("adapter", "provider"),
    [
        (ClaudeAdapter(), "claude"),
        (CodexAdapter(), "codex"),
        (AntigravityAdapter(), "antigravity"),
    ],
)
def test_real_cli_adapters_use_sealed_agent_runner(monkeypatch, adapter, provider):
    from src.runner import agent

    seen = {}

    def fake_run(prompt, **kwargs):
        seen.update(kwargs)
        return agent.AgentResult(
            ok=True, text=f"{provider} answer", returncode=0, duration_s=0.1)

    monkeypatch.setattr(agent, "run_agent", fake_run)
    assert adapter.generate("prompt", system_prompt="system", model="selected") == f"{provider} answer"
    assert seen["provider"] == provider
    assert seen["model"] == "selected"
    assert seen["allowed_tools"] == ()
    assert seen["sandbox"] == "read-only"
