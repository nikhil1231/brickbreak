"""HTTP-facing operations for the frozen research-director workflow.

The backend handler delegates here so the web app and CLI exercise the same
contracts, qualification gates, and one-shot executor rather than growing a
second research harness in the interface layer.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..contracts import MechanismDossier
from ..contracts.compiler import (
    CONTRACTS_DIR,
    EXECUTIONS_DIR,
    QUALIFICATIONS_DIR,
    _atomic_json,
    compile_qualification,
    load_qualification,
    save_contract,
)
from ..core import config
from ..council import (
    HOSTILE_REVIEW_SYSTEM_PROMPT,
    SCOUT_SYSTEM_PROMPT,
    ScoutLens,
    adjudicate_dossier,
    build_hostile_review_prompt,
    build_scout_prompt,
    parse_dossier_json,
    parse_hostile_review,
)
from ..firewall import load_exposure_log
from ..firewall.exposure import (
    WEEKLY_OUTCOME_ACCESS_CEILING,
    check_weekly_exposure_limit,
)
from ..persistence import store
from ..providers import (
    ProviderRole,
    ProviderType,
    SubscriptionPool,
    route_council_call,
)
from ..research_data.catalogue import DEFAULT as FEATURE_CATALOGUE
from ..runner.director import execute_contract
from ..runner.qualification import qualify_adjudication


DOSSIERS_DIR = config.METADATA_DIR / "research_store" / "dossiers"
ADJUDICATIONS_DIR = config.METADATA_DIR / "research_store" / "director" / "adjudications"


class DirectorAPIError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _dossier_path(dossier_id: str) -> Path:
    path = DOSSIERS_DIR / f"{dossier_id}.json"
    if not path.exists():
        raise DirectorAPIError(f"dossier {dossier_id!r} not found", 404)
    return path


def _adjudication_path(dossier_id: str) -> Path:
    path = ADJUDICATIONS_DIR / f"{dossier_id}.json"
    if not path.exists():
        raise DirectorAPIError(f"adjudication for {dossier_id!r} not found", 404)
    return path


def _summary_dossier(dossier: MechanismDossier) -> dict[str, Any]:
    return {
        **dossier.to_dict(),
        "stage": "data_gap" if dossier.has_data_gap else "dossier",
    }


def _read_json_files(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            value = json.loads(path.read_text())
            if isinstance(value, dict):
                out.append(value)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def state() -> dict[str, Any]:
    dossiers = []
    for raw in _read_json_files(DOSSIERS_DIR):
        try:
            dossiers.append(_summary_dossier(MechanismDossier.from_dict(raw)))
        except Exception:
            continue

    adjudications = _read_json_files(ADJUDICATIONS_DIR)
    qualifications = []
    for raw in _read_json_files(QUALIFICATIONS_DIR):
        try:
            qualifications.append(load_qualification(raw["qualification_id"]).to_dict())
        except Exception:
            continue

    contracts = []
    for raw in _read_json_files(CONTRACTS_DIR):
        try:
            contract = raw["contract"]
            lifecycle = raw["lifecycle"]
            contracts.append({**contract, "lifecycle": lifecycle})
        except (KeyError, TypeError):
            continue

    executions = _read_json_files(EXECUTIONS_DIR)
    entries = load_exposure_log()
    used, allowed = check_weekly_exposure_limit(entries)
    return {
        "dossiers": dossiers,
        "adjudications": adjudications,
        "qualifications": qualifications,
        "contracts": contracts,
        "executions": executions,
        "exposure": {
            "weekly_used": used,
            "weekly_ceiling": WEEKLY_OUTCOME_ACCESS_CEILING,
            "allowed": allowed,
            "total_records": len(entries),
        },
    }


def discover(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        lens = ScoutLens(str(payload.get("lens") or ScoutLens.MARKET_STRUCTURE.value))
        preferred = ProviderType(str(payload.get("provider") or "claude"))
    except ValueError as exc:
        raise DirectorAPIError(str(exc)) from exc
    if preferred not in (ProviderType.CLAUDE, ProviderType.CODEX):
        raise DirectorAPIError("only claude and codex are supported scout lanes")

    hypotheses = store.list_hypotheses()
    graveyard = [
        f"{h.id} [{h.family}/{h.status}] {h.title}: {h.rationale}"
        for h in hypotheses if h.status in ("rejected", "decayed", "superseded")
    ]
    prompt = build_scout_prompt(
        lens=lens,
        domain_hint=str(payload.get("hint") or ""),
        catalogue_features=[
            f"{feature.name} ({feature.available_as_of}, "
            f"{'PIT' if feature.point_in_time else 'not-PIT'})"
            for feature in FEATURE_CATALOGUE
        ],
        graveyard_notes=graveyard,
    )
    response, provider = route_council_call(
        SubscriptionPool(), ProviderRole.SCOUT, prompt,
        system_prompt=SCOUT_SYSTEM_PROMPT, preferred_provider=preferred)
    response_id = hashlib.sha256(response.encode()).hexdigest()[:10].upper()
    dossier = parse_dossier_json(
        response,
        dossier_id=f"DOS_{lens.value.upper()[:4]}_{response_id}",
        hypothesis_id=f"PROP_{response_id}",
        family=str(payload.get("family") or "general"),
        proposer=f"{provider.value}:scout_{lens.value}",
    )
    path = _atomic_json(DOSSIERS_DIR / f"{dossier.dossier_id}.json", dossier.to_dict())
    return {"dossier": _summary_dossier(dossier), "path": str(path)}


def attack(payload: dict[str, Any]) -> dict[str, Any]:
    dossier_id = str(payload.get("dossier_id") or "").strip()
    dossier = MechanismDossier.from_dict(json.loads(_dossier_path(dossier_id).read_text()))
    existing_path = ADJUDICATIONS_DIR / f"{dossier.dossier_id}.json"
    if existing_path.exists():
        return {
            "adjudication": json.loads(existing_path.read_text()),
            "path": str(existing_path),
        }
    proposer_provider = None
    try:
        proposer_provider = ProviderType(dossier.proposer.split(":", 1)[0])
    except ValueError:
        pass
    reviewer_raw = str(payload.get("provider") or "auto")
    try:
        reviewer = None if reviewer_raw == "auto" else ProviderType(reviewer_raw)
    except ValueError as exc:
        raise DirectorAPIError(str(exc)) from exc
    response, provider = route_council_call(
        SubscriptionPool(), ProviderRole.CRITIC,
        build_hostile_review_prompt(dossier),
        system_prompt=HOSTILE_REVIEW_SYSTEM_PROMPT,
        preferred_provider=reviewer,
        proposer_provider=proposer_provider,
    )
    model_review = parse_hostile_review(response, provider.value)
    adjudication = adjudicate_dossier(
        dossier, additional_reviews=(model_review,))
    path = _atomic_json(
        ADJUDICATIONS_DIR / f"{dossier.dossier_id}.json",
        adjudication.to_dict())
    return {"adjudication": adjudication.to_dict(), "path": str(path)}


def qualify(payload: dict[str, Any]) -> dict[str, Any]:
    dossier_id = str(payload.get("dossier_id") or "").strip()
    signal_name = str(payload.get("signal_name") or "").strip()
    if not signal_name:
        raise DirectorAPIError("signal_name is required")
    adjudication = json.loads(_adjudication_path(dossier_id).read_text())
    artifact, path = qualify_adjudication(
        adjudication,
        signal_name=signal_name,
        provider=str(payload.get("provider") or "claude"),
        model=str(payload.get("model") or "") or None,
        dataset_version=str(payload.get("dataset_version") or "v1"),
    )
    return {"qualification": artifact.to_dict(), "path": str(path)}


def compile_contract(payload: dict[str, Any]) -> dict[str, Any]:
    qualification_id = str(payload.get("qualification_id") or "").strip()
    qualification = load_qualification(qualification_id)
    contract, lifecycle, batch = compile_qualification(
        qualification,
        reviewer=str(payload.get("reviewer") or "human_owner"),
        cost_round_trip_bps=float(payload.get("cost_bps", 40.0)),
        capacity_limit_inr=float(payload.get("capacity_inr", 1_000_000.0)),
        min_significance_t=float(payload.get("min_t", 2.5)),
    )
    path = save_contract(contract, lifecycle)
    return {
        "contract": contract.to_dict(),
        "lifecycle": lifecycle.to_dict(),
        "batch": batch.to_dict(),
        "path": str(path),
    }


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("confirm_outcome_access") is not True:
        raise DirectorAPIError(
            "confirm_outcome_access must be true before outcomes are revealed")
    contract_id = str(payload.get("contract_id") or "").strip()
    result, path = execute_contract(
        contract_id, enroll_forward=bool(payload.get("enroll_forward", False)))
    return {"execution": result, "path": str(path)}


POST_OPERATIONS = {
    "/api/director/discover": discover,
    "/api/director/attack": attack,
    "/api/director/qualify": qualify,
    "/api/director/compile": compile_contract,
    "/api/director/execute": execute,
}


def dispatch_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    operation = POST_OPERATIONS.get(path)
    if operation is None:
        raise DirectorAPIError("director operation not found", 404)
    try:
        return operation(payload)
    except DirectorAPIError:
        raise
    except FileNotFoundError as exc:
        raise DirectorAPIError(str(exc), 404) from exc
    except Exception as exc:
        raise DirectorAPIError(f"{type(exc).__name__}: {exc}") from exc
