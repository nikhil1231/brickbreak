"""The forward lane: evidence that accrues one session a day (PLAN.md §5.2).

A shuffled test set is interleaved with training in time, so it can answer
"does this work across regimes?" and cannot answer "does it still work?".
`forward` is every session after the dataset version was created — strictly
chronological, never shuffled, and for any descendant of H024, H026 or
H034-H038 it is the only unqualified confirmatory evidence left, because those
families have already spent 2020-2023.

IT IS EMPTY, AND THAT IS THE NORMAL STATE
At version creation the forward partition holds zero sessions and it grows by
one per trading day. Nothing can reach `validated` until the data exists.
`status()` says so in those words rather than returning an empty result that
reads like a bug, because an interface that looks broken gets worked around.

WHAT THIS MODULE DOES
Registers a signal for accrual (keeping the source that computes it), and
re-scores every registered signal against whatever forward sessions exist.
It cannot manufacture data; it makes sure that when the data arrives, the
evidence is recorded without anyone having to remember to do it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..core import config
from ..persistence import Evidence, store
from ..research_data import frame, splits

REGISTRY_PATH = config.METADATA_DIR / "research_store" / "forward_registry.json"


@dataclass
class Registration:
    """A signal promoted to the forward lane."""
    signal_name: str
    hypothesis_id: str
    source: str                       # the compute() that defines it
    primary_horizon: int = 10
    dataset_version: str = "v1"
    registered_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    registered_from_exploration: str = ""
    last_accrued_session: str = ""
    n_evidence: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def _load() -> list[Registration]:
    if not REGISTRY_PATH.exists():
        return []
    return [Registration(**r) for r in
            json.loads(REGISTRY_PATH.read_text()).get("registrations", [])]


def _save(regs: list[Registration]) -> Path:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(
        {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
         "registrations": [r.to_dict() for r in regs]}, indent=2) + "\n")
    return REGISTRY_PATH


def status(version: str = "v1") -> dict[str, Any]:
    """How much forward data exists, in words that do not read as a failure."""
    manifest = splits.load(version)
    start = manifest["forward"]["start"]
    sess = splits.sessions()
    have = int((sess >= pd.Timestamp(start)).sum())
    regs = _load()

    if have == 0:
        note = (f"The forward lane opens at {start} and holds no sessions yet. "
                f"This is the expected state at version creation, not a "
                f"failure: it fills at one session per trading day. Nothing "
                f"can be validated until it does, and for the opening-window "
                f"and resilience families it is the only clean lane left.")
    else:
        note = (f"{have} forward sessions since {start}. "
                f"{len(regs)} signal(s) accruing.")

    return {
        "start": start,
        "n_sessions": have,
        "n_registered": len(regs),
        "registrations": [r.to_dict() for r in regs],
        "ready": have > 0,
        "note": note,
    }


def register(signal_name: str, hypothesis_id: str, source: str,
             primary_horizon: int = 10, dataset_version: str = "v1",
             exploration_id: str = "") -> Registration:
    """Enrol a signal so forward evidence accrues without anyone remembering."""
    regs = _load()
    for r in regs:
        if r.signal_name == signal_name and r.hypothesis_id == hypothesis_id:
            return r
    reg = Registration(signal_name=signal_name, hypothesis_id=hypothesis_id,
                       source=source, primary_horizon=primary_horizon,
                       dataset_version=dataset_version,
                       registered_from_exploration=exploration_id)
    regs.append(reg)
    _save(regs)
    return reg


def _compute_from_source(source: str, df: pd.DataFrame) -> pd.Series:
    ns: dict[str, Any] = {}
    exec(compile(source, "<registered_signal>", "exec"), ns)   # noqa: S102
    fn = ns.get("compute")
    if fn is None:
        raise ValueError("registered source defines no compute()")
    return fn(df)


def accrue(version: str = "v1", save: bool = True) -> dict[str, Any]:
    """Score every registered signal on the forward sessions that now exist."""
    st = status(version)
    if not st["ready"]:
        return {"accrued": 0, "note": st["note"]}

    from ..alpha_eval import diagnostics

    regs = _load()
    df = frame.load_daily_panel(version=version, partition="forward",
                                asof_open=True, include_context=True)
    out = []
    for reg in regs:
        h = reg.primary_horizon
        d = df.copy()
        d[f"fwd_ret_{h}d_pct"] = frame.forward_return(d, horizon=h,
                                                      version=version)
        try:
            d[reg.signal_name] = _compute_from_source(reg.source, d)
        except Exception as exc:                       # noqa: BLE001
            out.append({"signal": reg.signal_name, "error": str(exc)})
            continue

        ic = diagnostics.rank_ic(d, reg.signal_name, f"fwd_ret_{h}d_pct",
                                 horizon=h)
        if save:
            ev = Evidence(
                id=f"EV_FWD_{reg.signal_name}_{datetime.now():%Y%m%d_%H%M%S}",
                hypothesis_id=reg.hypothesis_id,
                signal_id=reg.signal_name,
                exploration_id=reg.registered_from_exploration,
                role="confirmatory",
                dataset_version=version,
                partition="forward",
                metrics={"mean_ic": ic["mean_ic"], "ic_t_stat": ic["t_stat"],
                         "n_sessions": ic["n_sessions"],
                         "effective_n": ic.get("effective_n")},
                verdict_statement=(
                    f"Forward lane, {ic['n_sessions']} sessions since "
                    f"{st['start']}: mean IC {ic['mean_ic']}, t {ic['t_stat']}."),
            )
            store.add_evidence(ev)
            reg.n_evidence += 1
            reg.last_accrued_session = str(d["date"].max())[:10]
        out.append({"signal": reg.signal_name, "mean_ic": ic["mean_ic"],
                    "t_stat": ic["t_stat"], "n_sessions": ic["n_sessions"]})

    if save:
        _save(regs)
    return {"accrued": len(out), "results": out, "note": st["note"]}
