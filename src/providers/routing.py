"""Asymmetric provider routing rules (PLAN.md §4, §9 and Stage Z).

A provider or model lane may propose or approve a dossier, but not both.
Independent first passes occur before cross-agent deliberation.
"""
from __future__ import annotations

import logging

from .pool import NoFallbackError, ProviderRole, ProviderType, SubscriptionPool

logger = logging.getLogger(__name__)


class AsymmetricRoleError(PermissionError):
    pass


def validate_asymmetric_assignment(proposer_provider: ProviderType,
                                   reviewer_provider: ProviderType,
                                   context: str = "") -> None:
    """Ensure proposing and reviewing roles are assigned to separate providers."""
    if proposer_provider == reviewer_provider and proposer_provider != ProviderType.MOCK:
        raise AsymmetricRoleError(
            f"Proposer and reviewer are both assigned to {proposer_provider.value!r} in {context}. "
            f"A provider may propose or approve a dossier, not both (PLAN.md §4)."
        )


def route_council_call(pool: SubscriptionPool,
                       role: ProviderRole,
                       prompt: str,
                       system_prompt: str = "",
                       model: str = "",
                       preferred_provider: ProviderType | None = None,
                       proposer_provider: ProviderType | None = None) -> tuple[str, ProviderType]:
    """Route a council call ensuring asymmetric separation from proposer."""
    target = preferred_provider
    if target is None:
        if role == ProviderRole.SCOUT:
            preference = (ProviderType.CLAUDE, ProviderType.CODEX,
                          ProviderType.ANTIGRAVITY)
        elif role in (ProviderRole.CRITIC, ProviderRole.ADJUDICATOR):
            preference = (ProviderType.CODEX, ProviderType.CLAUDE,
                          ProviderType.ANTIGRAVITY)
        else:
            preference = (ProviderType.CLAUDE, ProviderType.CODEX,
                          ProviderType.ANTIGRAVITY)
        available = set(pool.available_provider_types(
            exclude=(proposer_provider,) if proposer_provider else ()))
        target = next((provider for provider in preference if provider in available), None)
        if target is None:
            raise NoFallbackError(
                f"No available provider can serve role {role.value!r} while remaining "
                "independent of the proposer")

    if proposer_provider is not None and role != ProviderRole.SCOUT:
        validate_asymmetric_assignment(proposer_provider, target, context=f"Role {role.value}")

    resp = pool.dispatch(
        target, prompt=prompt, system_prompt=system_prompt,
        model=model, role=role)
    return resp, target
