"""HTTP-facing operations for the frozen research-director workflow.

The backend handler delegates here so the web app and CLI exercise the same
contracts, qualification gates, and one-shot executor rather than growing a
second research harness in the interface layer.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from typing import Any

from ..contracts import MechanismDossier
from ..contracts.compiler import (
    CONTRACTS_DIR,
    EXECUTIONS_DIR,
    QUALIFICATIONS_DIR,
    _atomic_json,
    compile_batch,
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
from ..runner.director import WITHDRAWALS_DIR, execute_contract
from ..runner.qualification import qualify_adjudication


DOSSIERS_DIR = config.METADATA_DIR / "research_store" / "dossiers"
ADJUDICATIONS_DIR = config.METADATA_DIR / "research_store" / "director" / "adjudications"
RUNS_DIR = config.METADATA_DIR / "research_store" / "director" / "runs"


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


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _valid_run_id(value: str) -> bool:
    return 8 <= len(value) <= 100 and all(
        character.isalnum() or character in "_-" for character in value)


def _run_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def _load_run(run_id: str) -> dict[str, Any] | None:
    path = _run_path(run_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _find_run_for_dossier(dossier_id: str) -> dict[str, Any] | None:
    if not dossier_id:
        return None
    return next((run for run in _read_json_files(RUNS_DIR)
                 if run.get("dossier_id") == dossier_id), None)


def _save_run(run: dict[str, Any]) -> dict[str, Any]:
    run["updated_at"] = _now()
    _atomic_json(_run_path(str(run["run_id"])), run)
    return run


def _begin_run(stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Persist an operation before any provider or outcome-bearing work starts."""
    requested_id = str(payload.get("run_id") or "").strip()
    dossier_id = str(payload.get("dossier_id") or "").strip()
    existing = _load_run(requested_id) if requested_id else None
    if existing is None and not requested_id:
        existing = _find_run_for_dossier(dossier_id)
    if existing is not None:
        run_id = str(existing["run_id"])
    elif requested_id:
        run_id = requested_id
    elif stage == "discover":
        run_id = f"RUN_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8].upper()}"
    else:
        return None
    if not _valid_run_id(run_id):
        raise DirectorAPIError("run_id must contain only letters, numbers, '_' or '-'")

    payload["run_id"] = run_id
    now = _now()
    run = existing or {
        "run_id": run_id,
        "dossier_id": dossier_id or None,
        "claim": str(payload.get("hint") or "").strip() or None,
        "created_at": now,
    }
    run.update({
        "stage": stage,
        "status": "running",
        "error": None,
        "provider": str(payload.get("provider") or run.get("provider") or ""),
        "model": str(payload.get("model") or run.get("model") or ""),
        "config": {
            key: payload[key] for key in (
                "lens", "family", "hint", "signal_name", "cost_bps",
                "capacity_inr", "min_t", "deterministic_only",
            ) if key in payload
        },
    })
    return _save_run(run)


def _finish_run(run: dict[str, Any] | None, stage: str,
                result: dict[str, Any]) -> dict[str, Any] | None:
    if run is None:
        return None
    dossier = result.get("dossier")
    if not isinstance(dossier, dict):
        for container in ("adjudication", "qualification"):
            candidate = result.get(container)
            if isinstance(candidate, dict) and isinstance(candidate.get("dossier"), dict):
                dossier = candidate["dossier"]
                break
    if isinstance(dossier, dict):
        run["dossier_id"] = dossier.get("dossier_id") or run.get("dossier_id")
        run["claim"] = dossier.get("claim") or run.get("claim")

    next_stage = {
        "discover": "attack", "attack": "qualify", "qualify": "compile",
        "compile": "execute", "execute": "complete",
    }[stage]
    status = "ready"
    if stage == "attack":
        adjudication = result.get("adjudication") or {}
        if not adjudication.get("approved"):
            status = "stopped"
    elif stage == "qualify":
        qualification = result.get("qualification") or {}
        if not qualification.get("approved"):
            status = "stopped"
    elif stage == "execute":
        execution = result.get("execution") or {}
        status = "complete" if execution.get("status") == "succeeded" else "stopped"
    run.update({
        "stage": next_stage if status in ("ready", "complete") else stage,
        "status": status,
        "last_completed_stage": stage,
        "error": None,
    })
    return _save_run(run)


def _fail_run(run: dict[str, Any] | None, stage: str, exc: Exception) -> None:
    if run is None:
        return
    run.update({
        "stage": stage,
        "status": "failed",
        "error": f"{type(exc).__name__}: {exc}",
    })
    _save_run(run)


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
    withdrawals = _read_json_files(WITHDRAWALS_DIR)
    entries = load_exposure_log()
    used, allowed = check_weekly_exposure_limit(entries)
    return {
        "runs": _read_json_files(RUNS_DIR),
        "dossiers": dossiers,
        "adjudications": adjudications,
        "qualifications": qualifications,
        "contracts": contracts,
        "executions": executions,
        "withdrawals": withdrawals,
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
    if preferred not in (ProviderType.CLAUDE, ProviderType.CODEX, ProviderType.ANTIGRAVITY):
        raise DirectorAPIError("only claude, codex and antigravity are supported scout lanes")

    hypotheses = store.list_hypotheses()
    ledger_context = [
        f"{h.id} [{h.family}/{h.status}] {h.title}: {h.rationale}"
        for h in hypotheses
    ]
    prompt = build_scout_prompt(
        lens=lens,
        domain_hint=str(payload.get("hint") or ""),
        catalogue_features=[
            f"{feature.name} ({feature.available_as_of}, "
            f"{'PIT' if feature.point_in_time else 'not-PIT'})"
            for feature in FEATURE_CATALOGUE
        ],
        graveyard_notes=ledger_context,
    )
    selected_model = str(payload.get("model") or "")
    response, provider = route_council_call(
        SubscriptionPool(), ProviderRole.SCOUT, prompt,
        system_prompt=SCOUT_SYSTEM_PROMPT, model=selected_model,
        preferred_provider=preferred)
    response_id = hashlib.sha256(response.encode()).hexdigest()[:10].upper()
    dossier = parse_dossier_json(
        response,
        dossier_id=f"DOS_{lens.value.upper()[:4]}_{response_id}",
        hypothesis_id=f"PROP_{response_id}",
        family=str(payload.get("family") or "general"),
        proposer=(f"{provider.value}:scout_{lens.value};"
                  f"model={selected_model or 'cli-default'}"),
    )
    path = _atomic_json(DOSSIERS_DIR / f"{dossier.dossier_id}.json", dossier.to_dict())
    return {"dossier": _summary_dossier(dossier), "path": str(path)}


def attack(payload: dict[str, Any]) -> dict[str, Any]:
    dossier_id = str(payload.get("dossier_id") or "").strip()
    dossier = MechanismDossier.from_dict(json.loads(_dossier_path(dossier_id).read_text()))
    existing_path = ADJUDICATIONS_DIR / f"{dossier.dossier_id}.json"
    if existing_path.exists():
        existing = json.loads(existing_path.read_text())
        if bool(payload.get("waive_failed_independent_attack", False)):
            if existing.get("independent_attack_waiver"):
                return {"adjudication": existing, "path": str(existing_path)}
            if existing.get("approved"):
                raise DirectorAPIError(
                    "an approved independent attack does not need a waiver", 409)
            failed_model_reviews = [
                review for review in existing.get("reviews", [])
                if str(review.get("critic_role", "")).startswith(
                    "independent_model_critic:")
                and review.get("approved") is False
            ]
            if not failed_model_reviews:
                raise DirectorAPIError(
                    "no failed independent model attack is available to waive", 409)

            deterministic = adjudicate_dossier(dossier).to_dict()
            if not deterministic.get("approved"):
                raise DirectorAPIError(
                    "the dossier still fails deterministic gates; the independent "
                    "attack is not the blocking condition", 409)

            waived = {
                **deterministic,
                # Preserve the rejected review, its dissents and the dossier hash
                # that qualification will freeze. A waiver changes the routing
                # decision; it does not rewrite the historical criticism.
                "dossier": existing.get("dossier", deterministic["dossier"]),
                "reviews": existing.get("reviews", deterministic["reviews"]),
                "all_dissents": existing.get(
                    "all_dissents", deterministic["all_dissents"]),
                "independent_attack_waiver": {
                    "status": "waived_after_failure",
                    "waived_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "reason": str(payload.get("waiver_reason") or (
                        "Owner elected to continue without treating the failed "
                        "independent model attack as a blocking gate."
                    )),
                    "original_verdict": str(existing.get("verdict") or "REJECTED"),
                    "failed_reviews": failed_model_reviews,
                    "original_all_dissents": existing.get("all_dissents", []),
                },
                "verdict": (
                    "APPROVED AFTER OWNER WAIVER. The failed independent model "
                    "attack and all objections remain attached; deterministic "
                    "gates passed."
                ),
            }
            path = _atomic_json(existing_path, waived)
            return {"adjudication": waived, "path": str(path)}
        return {
            "adjudication": existing,
            "path": str(existing_path),
        }
    proposer_provider = None
    try:
        proposer_provider = ProviderType(dossier.proposer.split(":", 1)[0])
    except ValueError:
        pass
    reviewer_raw = str(payload.get("provider") or "auto")
    selected_model = str(payload.get("model") or "")
    try:
        reviewer = None if reviewer_raw == "auto" else ProviderType(reviewer_raw)
    except ValueError as exc:
        raise DirectorAPIError(str(exc)) from exc

    extra_reviews = ()
    deterministic_only = bool(payload.get("deterministic_only", False))
    if not deterministic_only:
        response, provider = route_council_call(
            SubscriptionPool(), ProviderRole.CRITIC,
            build_hostile_review_prompt(dossier),
            system_prompt=HOSTILE_REVIEW_SYSTEM_PROMPT,
            model=selected_model,
            preferred_provider=reviewer,
            proposer_provider=proposer_provider,
        )
        model_review = parse_hostile_review(
            response, provider.value, selected_model)
        extra_reviews = (model_review,)

    adjudication = adjudicate_dossier(
        dossier, additional_reviews=extra_reviews)
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
    raw_ids = payload.get("qualification_ids")
    if raw_ids is None:
        raw_ids = [payload.get("qualification_id")]
    if not isinstance(raw_ids, list):
        raise DirectorAPIError("qualification_ids must be a list")
    ids = [str(value or "").strip() for value in raw_ids]
    if not ids or any(not value for value in ids):
        raise DirectorAPIError("at least one qualification_id is required")
    qualifications = [load_qualification(value) for value in ids]
    contracts, lifecycles, batch = compile_batch(
        qualifications,
        reviewer=str(payload.get("reviewer") or "human_owner"),
        cost_round_trip_bps=float(payload.get("cost_bps", 40.0)),
        capacity_limit_inr=float(payload.get("capacity_inr", 1_000_000.0)),
        min_significance_t=float(payload.get("min_t", 2.5)),
    )
    paths = [save_contract(contract, lifecycle)
             for contract, lifecycle in zip(contracts, lifecycles)]
    return {
        "contract": contracts[0].to_dict() if len(contracts) == 1 else None,
        "lifecycle": lifecycles[0].to_dict() if len(lifecycles) == 1 else None,
        "contracts": [contract.to_dict() for contract in contracts],
        "lifecycles": [lifecycle.to_dict() for lifecycle in lifecycles],
        "batch": batch.to_dict(),
        "path": str(paths[0]) if len(paths) == 1 else None,
        "paths": [str(path) for path in paths],
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
    stage = path.rsplit("/", 1)[-1]
    run = _begin_run(stage, payload)
    try:
        result = operation(payload)
        persisted = _finish_run(run, stage, result)
        return {**result, **({"run": persisted} if persisted else {})}
    except DirectorAPIError as exc:
        _fail_run(run, stage, exc)
        raise
    except FileNotFoundError as exc:
        _fail_run(run, stage, exc)
        raise DirectorAPIError(str(exc), 404) from exc
    except Exception as exc:
        _fail_run(run, stage, exc)
        raise DirectorAPIError(f"{type(exc).__name__}: {exc}") from exc
