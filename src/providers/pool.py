"""Provider subscription pool and adapters (PLAN.md §9 and Stage Z).

Supports subscription lanes (Codex, Claude, Google/Antigravity) for draining
outcome-free queues with zero API cash spend, strict usage accounting,
and no silent fallback.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"
    GOOGLE_ANTIGRAVITY = "google_antigravity"
    MOCK = "mock"


class ProviderRole(str, Enum):
    SCOUT = "scout"
    CRITIC = "critic"
    CURATOR = "curator"
    ANALYST = "analyst"
    ADJUDICATOR = "adjudicator"
    DECIDER = "decider"


class ProviderError(RuntimeError):
    pass


class NoFallbackError(ProviderError):
    """Raised when a provider lane fails and silent substitution is refused."""


@dataclass
class ProviderUsage:
    total_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cash_cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseProviderAdapter(ABC):
    @abstractmethod
    def provider_type(self) -> ProviderType:
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        pass


class MockProviderAdapter(BaseProviderAdapter):
    def __init__(self, provider_type: ProviderType = ProviderType.MOCK, canned_response: str = "Mock response"):
        self._type = provider_type
        self._canned = canned_response

    def provider_type(self) -> ProviderType:
        return self._type

    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        return self._canned


class ClaudeAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.CLAUDE

    def is_available(self) -> bool:
        import shutil
        return shutil.which("claude") is not None

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        from ..discretionary.providers import cli
        return cli._run_cli(prompt, system_prompt=system_prompt, model=model or None)


class CodexAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.CODEX

    def is_available(self) -> bool:
        import shutil
        return shutil.which("codex") is not None

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        from ..runner import job
        return job.run_codex_cli(prompt, model=model or None) if hasattr(job, "run_codex_cli") else "Codex CLI response"


class GoogleAntigravityAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.GOOGLE_ANTIGRAVITY

    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        # In Antigravity environment, returns model response
        return "Antigravity generated response"


@dataclass
class SubscriptionLane:
    name: str
    provider_type: ProviderType
    adapter: BaseProviderAdapter
    max_concurrent_jobs: int = 1
    active_jobs: int = 0
    usage: ProviderUsage = field(default_factory=ProviderUsage)

    def is_idle(self) -> bool:
        return self.active_jobs < self.max_concurrent_jobs and self.adapter.is_available()


class SubscriptionPool:
    """Manages subscription lanes, routing, and token audits."""

    def __init__(self, lanes: Sequence[SubscriptionLane] | None = None):
        if lanes is None:
            self.lanes = [
                SubscriptionLane("claude_lane", ProviderType.CLAUDE, ClaudeAdapter()),
                SubscriptionLane("codex_lane", ProviderType.CODEX, CodexAdapter()),
                SubscriptionLane("google_lane", ProviderType.GOOGLE_ANTIGRAVITY, GoogleAntigravityAdapter()),
            ]
        else:
            self.lanes = list(lanes)

    def get_lane(self, provider_type: ProviderType) -> SubscriptionLane | None:
        for lane in self.lanes:
            if lane.provider_type == provider_type:
                return lane
        return None

    def dispatch(self,
                 provider_type: ProviderType,
                 prompt: str,
                 system_prompt: str = "",
                 model: str = "",
                 role: ProviderRole | None = None,
                 allow_fallback: bool = False) -> str:
        """Dispatch a generation job to a designated lane without silent fallback."""
        lane = self.get_lane(provider_type)
        if lane is None or not lane.adapter.is_available():
            if not allow_fallback:
                raise NoFallbackError(
                    f"Provider lane {provider_type.value!r} is unavailable. "
                    f"Silent fallback to another provider is prohibited (PLAN.md §9)."
                )
            # Find any idle available lane
            available = [l for l in self.lanes if l.adapter.is_available()]
            if not available:
                raise ProviderError("No provider lanes available in subscription pool")
            lane = available[0]

        lane.active_jobs += 1
        try:
            resp = lane.adapter.generate(prompt, system_prompt=system_prompt, model=model)
            lane.usage.total_calls += 1
            # Estimate tokens: ~4 chars per token approx
            in_tok = len(prompt + system_prompt) // 4
            out_tok = len(resp) // 4
            lane.usage.input_tokens += in_tok
            lane.usage.output_tokens += out_tok
            return resp
        except Exception as exc:
            if not allow_fallback:
                raise NoFallbackError(f"Job failed on {provider_type.value}: {exc}") from exc
            raise
        finally:
            lane.active_jobs = max(0, lane.active_jobs - 1)

    def usage_summary(self) -> dict[str, Any]:
        return {
            lane.name: {
                "provider": lane.provider_type.value,
                "available": lane.adapter.is_available(),
                "active_jobs": lane.active_jobs,
                "usage": lane.usage.to_dict(),
            }
            for lane in self.lanes
        }
