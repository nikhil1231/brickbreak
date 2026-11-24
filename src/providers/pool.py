"""Provider subscription pool and adapters (PLAN.md §9 and Stage Z).

Supports subscription lanes (Codex, Claude, Google/Antigravity) for draining
outcome-free queues with zero API cash spend, strict usage accounting,
and no silent fallback.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Sequence

logger = logging.getLogger(__name__)


class ProviderType(str, Enum):
    CODEX = "codex"
    CLAUDE = "claude"
    ANTIGRAVITY = "antigravity"
    GOOGLE_ANTIGRAVITY = "antigravity"
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


class ProviderBusyError(ProviderError):
    """Raised when a subscription lane has reached its concurrency limit."""


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


def _run_cli_provider(provider: str, prompt: str,
                      system_prompt: str = "", model: str = "") -> str:
    """Run a subscription CLI through the existing sealed agent adapter."""
    from pathlib import Path

    from ..runner import agent

    full_prompt = f"{system_prompt}\n\n---\n\n{prompt}" if system_prompt else prompt
    with tempfile.TemporaryDirectory(prefix=f"council_{provider}_") as tmp:
        result = agent.run_agent(
            full_prompt,
            cwd=Path(tmp),
            timeout_s=900,
            max_turns=1,
            allowed_tools=(),
            model=model or None,
            provider=provider,
            sandbox="read-only",
        )
    if not result.ok:
        detail = result.stderr or f"{provider} CLI exited with {result.returncode}"
        raise ProviderError(detail)
    if not result.text.strip():
        raise ProviderError(f"{provider} CLI returned an empty response")
    return result.text


class ClaudeAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.CLAUDE

    def is_available(self) -> bool:
        from ..runner import agent
        return agent.available(provider="claude")

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        return _run_cli_provider("claude", prompt, system_prompt, model)


class CodexAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.CODEX

    def is_available(self) -> bool:
        from ..runner import agent
        return agent.available(provider="codex")

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        return _run_cli_provider("codex", prompt, system_prompt, model)


class AntigravityAdapter(BaseProviderAdapter):
    def provider_type(self) -> ProviderType:
        return ProviderType.ANTIGRAVITY

    def is_available(self) -> bool:
        from ..runner import agent
        return agent.available(provider="antigravity")

    def generate(self, prompt: str, system_prompt: str = "", model: str = "") -> str:
        return _run_cli_provider("antigravity", prompt, system_prompt, model)


# Reader compatibility for artifacts/tests written while the lane used its
# longer provisional name.  The production identity is `antigravity`.
GoogleAntigravityAdapter = AntigravityAdapter


@dataclass
class SubscriptionLane:
    name: str
    provider_type: ProviderType
    adapter: BaseProviderAdapter
    max_concurrent_jobs: int = 1
    active_jobs: int = 0
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    _lock: threading.Lock = field(default_factory=threading.Lock,
                                  init=False, repr=False, compare=False)

    def is_idle(self) -> bool:
        with self._lock:
            return (self.active_jobs < self.max_concurrent_jobs
                    and self.adapter.is_available())

    def acquire(self) -> bool:
        with self._lock:
            if (self.active_jobs >= self.max_concurrent_jobs
                    or not self.adapter.is_available()):
                return False
            self.active_jobs += 1
            return True

    def release(self) -> None:
        with self._lock:
            self.active_jobs = max(0, self.active_jobs - 1)


class SubscriptionPool:
    """Manages subscription lanes, routing, and token audits."""

    def __init__(self, lanes: Sequence[SubscriptionLane] | None = None):
        if lanes is None:
            self.lanes = [
                SubscriptionLane("claude_lane", ProviderType.CLAUDE, ClaudeAdapter()),
                SubscriptionLane("codex_lane", ProviderType.CODEX, CodexAdapter()),
                SubscriptionLane("antigravity_lane", ProviderType.ANTIGRAVITY, AntigravityAdapter()),
            ]
        else:
            self.lanes = list(lanes)

    def get_lane(self, provider_type: ProviderType) -> SubscriptionLane | None:
        for lane in self.lanes:
            if lane.provider_type == provider_type:
                return lane
        return None

    def available_provider_types(self,
                                 exclude: Sequence[ProviderType] = ()) -> list[ProviderType]:
        excluded = set(exclude)
        return [lane.provider_type for lane in self.lanes
                if lane.provider_type not in excluded and lane.is_idle()]

    def dispatch(self,
                 provider_type: ProviderType,
                 prompt: str,
                 system_prompt: str = "",
                 model: str = "",
                 role: ProviderRole | None = None,
                 allow_fallback: bool = False) -> str:
        """Dispatch a generation job to a designated lane without silent fallback."""
        lane = self.get_lane(provider_type)
        if lane is None or not lane.is_idle():
            if not allow_fallback:
                state = "missing, unavailable, or busy"
                raise NoFallbackError(
                    f"Provider lane {provider_type.value!r} is {state}. "
                    f"Silent fallback to another provider is prohibited (PLAN.md §9)."
                )
            available = [l for l in self.lanes if l.is_idle()]
            if not available:
                raise ProviderError("No provider lanes available in subscription pool")
            lane = available[0]

        if not lane.acquire():
            raise ProviderBusyError(
                f"Provider lane {lane.name!r} reached its concurrency limit")
        try:
            lane.usage.total_calls += 1
            lane.usage.input_tokens += max(1, len(prompt + system_prompt) // 4)
            resp = lane.adapter.generate(prompt, system_prompt=system_prompt, model=model)
            lane.usage.output_tokens += max(1, len(resp) // 4)
            return resp
        except Exception as exc:
            if not allow_fallback:
                raise NoFallbackError(f"Job failed on {provider_type.value}: {exc}") from exc
            raise
        finally:
            lane.release()

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
