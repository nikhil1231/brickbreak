"""The forward lane: evidence that accrues one session a day (the refactor plan §5.2).

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
import hashlib
import tempfile
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
    """A signal, distilled rule, or replay promoted to the forward lane."""
    signal_name: str
    hypothesis_id: str
    source: str                       # the compute() that defines it
    primary_horizon: int = 10
    dataset_version: str = "v1"
    registered_at: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    registered_from_exploration: str = ""
    kind: str = "signal"              # "signal", "distilled_rule", "replay"
    replay_id: str = ""
    last_accrued_session: str = ""
    n_evidence: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def identity_hash(self) -> str:
        payload = {
            "signal_name": self.signal_name,
            "hypothesis_id": self.hypothesis_id,
            "source": self.source,
            "primary_horizon": self.primary_horizon,
            "dataset_version": self.dataset_version,
            "kind": self.kind,
            "replay_id": self.replay_id,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


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
             exploration_id: str = "", kind: str = "signal",
             replay_id: str = "") -> Registration:
    """Enrol a signal so forward evidence accrues without anyone remembering."""
    regs = _load()
    for r in regs:
        if r.signal_name == signal_name and r.hypothesis_id == hypothesis_id:
            candidate = Registration(
                signal_name=signal_name, hypothesis_id=hypothesis_id,
                source=source, primary_horizon=primary_horizon,
                dataset_version=dataset_version,
                registered_from_exploration=exploration_id,
                kind=kind, replay_id=replay_id,
            )
            if candidate.identity_hash != r.identity_hash:
                raise ValueError(
                    f"forward identity {signal_name!r}/{hypothesis_id!r} is already "
                    "registered with different frozen semantics")
            return r
    reg = Registration(signal_name=signal_name, hypothesis_id=hypothesis_id,
                       source=source, primary_horizon=primary_horizon,
                       dataset_version=dataset_version,
                       registered_from_exploration=exploration_id,
                       kind=kind, replay_id=replay_id)
    regs.append(reg)
    _save(regs)
    return reg


def register_distilled_rule(rule_name: str, expression: str, rule_hash: str,
                            hypothesis_id: str, primary_horizon: int = 10,
                            dataset_version: str = "v1") -> Registration:
    """Register a distilled rule into the forward lane."""
    src = (
        f"def compute(df):\n"
        f"    import pandas as pd\n"
        f"    selected = df.query({expression!r}, engine='python')\n"
        f"    s = pd.Series(0.0, index=df.index)\n"
        f"    s.loc[selected.index] = 1.0\n"
        f"    return s\n"
    )
    return register(
        signal_name=f"distil_{rule_name}",
        hypothesis_id=hypothesis_id,
        source=src,
        primary_horizon=primary_horizon,
        dataset_version=dataset_version,
        exploration_id=f"distil:{rule_hash}",
        kind="distilled_rule",
    )


def register_replay(replay_id: str, hypothesis_id: str,
                    primary_horizon: int = 10, dataset_version: str = "v1"
                    ) -> Registration:
    """Register a discretionary replay identity for forward tracking."""
    return register(
        signal_name=f"replay:{replay_id}",
        hypothesis_id=hypothesis_id,
        source="",
        primary_horizon=primary_horizon,
        dataset_version=dataset_version,
        exploration_id=f"replay:{replay_id}",
        kind="replay",
        replay_id=replay_id,
    )



def _compute_from_source(source: str, df: pd.DataFrame) -> pd.Series:
    from .job import load_signal_fn
    with tempfile.TemporaryDirectory(prefix="brickbreak_forward_") as tmp:
        path = Path(tmp) / "signal.py"
        path.write_text(source)
        return load_signal_fn(path)(df)


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
        if reg.kind == "replay":
            out.append({
                "signal": reg.signal_name,
                "note": "replay forward accrual uses the discretionary adapter",
            })
            continue
        h = reg.primary_horizon
        d = df.copy()
        try:
            # Freeze the score before constructing any forward outcome.  A
            # registered function receives the same label-free capability as
            # a fresh experiment function.
            d[reg.signal_name] = _compute_from_source(reg.source, d)
        except Exception as exc:                       # noqa: BLE001
            out.append({"signal": reg.signal_name, "error": str(exc)})
            continue
        d[f"fwd_ret_{h}d_pct"] = frame.forward_return(d, horizon=h,
                                                      version=version)

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
