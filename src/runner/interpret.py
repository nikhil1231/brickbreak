"""Turn a fingerprint into a paragraph a human can act on (PLAN.md §5.11).

The deliverable of an exploration is not a table and not a transcript. It is
something like:

    Relative resilience contains a modest monotonic signal over 5-15 sessions.
    Strongest after broad drawdowns beyond X; largely disappears after
    controlling for sector momentum. Three follow-up hypotheses suggested.

The failure *class* stays rule-based — a deterministic taxonomy is the whole
point of `classifier.py`, and a model that could relabel NO_SIGNAL as
promising would defeat it. What is written here is the prose around the class,
and it is assembled from the numbers rather than invented: every clause below
is licensed by a specific field of the report.

With the CLI installed the same numbers get a fluency pass. Without it the
deterministic text stands on its own, which is why it is written to be
readable rather than to be a fallback.
"""
from __future__ import annotations

from typing import Any

from . import agent


def _fmt(x, nd=3, suffix=""):
    return "n/a" if x is None else f"{x:.{nd}f}{suffix}" if isinstance(x, float) else f"{x}{suffix}"


def _strength(ic: float | None, t: float | None) -> str:
    if ic is None or t is None:
        return "no measurable"
    a = abs(ic)
    if abs(t) < 2:
        return "no statistically distinguishable"
    if a < 0.01:
        return "a very small"
    if a < 0.03:
        return "a modest"
    if a < 0.06:
        return "a moderate"
    return "a large"


def write_interpretation(report: dict[str, Any], spec: Any,
                         failure_class: str,
                         next_moves: list[dict] | None = None,
                         cli: str | None = None,
                         agent_fn=None) -> str:
    """Compose the paragraph. Deterministic unless a worker is available."""
    text = _deterministic(report, spec, failure_class, next_moves or [])
    if agent_fn is None and not agent.available(cli):
        return text

    prompt = (
        "Rewrite the following experiment summary as 3-5 plain sentences for a "
        "quantitative researcher. Keep every number and every hedge exactly as "
        "given; do not add findings, do not speculate about mechanisms that "
        "are not stated, and do not make it sound more positive than it is. "
        "Return only the paragraph.\n\n" + text)
    try:
        import pathlib
        res = (agent_fn(prompt) if agent_fn else
               agent.run_agent(prompt, cwd=pathlib.Path.cwd(), timeout_s=180,
                               max_turns=2, allowed_tools=(), cli=cli))
        if res.ok and res.text.strip():
            return res.text.strip()
    except Exception:
        pass
    return text


def _deterministic(report: dict, spec: Any, failure_class: str,
                   next_moves: list[dict]) -> str:
    pc = report.get("predictive_content", {})
    ic = pc.get("primary_ic", {}) or {}
    decay = pc.get("ic_decay", []) or []
    q = report.get("quantiles", {}) or {}
    neu = report.get("neutralisation", {}) or {}
    mech = report.get("signal_mechanics", {}) or {}
    bt = (report.get("backtest") or {}).get("portfolio", {}) or {}

    name = getattr(spec, "signal_name", report.get("signal", "the signal"))
    horizon = getattr(spec, "primary_horizon", ic.get("horizon"))
    parts: list[str] = []

    # 1. what it contains, at the primary horizon
    parts.append(
        f"{name} shows {_strength(ic.get('mean_ic'), ic.get('t_stat'))} "
        f"cross-sectional signal at {horizon} sessions "
        f"(rank IC {_fmt(ic.get('mean_ic'), 4)}, t {_fmt(ic.get('t_stat'), 2)} "
        f"after the overlap correction, over {ic.get('n_sessions', 0)} sessions)."
    )

    # 2. does it hold across horizons
    live = [d for d in decay if d.get("t_stat") is not None
            and abs(d.get("t_stat") or 0) >= 2]
    if len(live) >= 2:
        hs = [d["horizon"] for d in live]
        parts.append(f"It survives the correction at {min(hs)}-{max(hs)} "
                     f"sessions, so it is not a single-horizon artefact.")
    elif len(live) == 1:
        parts.append(f"Only the {live[0]['horizon']}-session horizon clears "
                     f"|t|>2; a one-horizon result is usually a coincidence.")
    else:
        parts.append("No horizon clears |t|>2 once overlapping windows are "
                     "accounted for.")

    # 3. shape of the quantile profile — the thing worth looking at
    mono, spread = q.get("q5_monotonicity"), q.get("q5_spread_bps")
    if mono is not None and spread is not None:
        shape = ("an orderly monotonic slope" if abs(mono) >= 0.9 else
                 "a broadly ordered slope" if abs(mono) >= 0.6 else
                 "no reliable ordering")
        parts.append(f"The quintile profile shows {shape} "
                     f"(monotonicity {_fmt(mono, 2)}) with a Q5-Q1 spread of "
                     f"{_fmt(spread, 1)} bps.")
    if (q.get("q5_tie_pct") or 0) > 25:
        parts.append(f"{_fmt(q.get('q5_tie_pct'), 0)}% of scores are tied, so "
                     f"the bucketing is partly arbitrary.")

    # 4. is it just a factor
    ret = neu.get("ic_retention_pct")
    if ret is not None:
        if ret < 25:
            parts.append(f"Only {_fmt(ret, 0)}% of the IC survives "
                         f"neutralisation against market, sector, size, "
                         f"volatility and momentum — most of this is factor "
                         f"exposure, not a new bet.")
        elif ret < 70:
            parts.append(f"{_fmt(ret, 0)}% of the IC survives neutralisation; "
                         f"the rest is standard factor exposure.")
        else:
            parts.append(f"{_fmt(ret, 0)}% of the IC survives neutralisation, "
                         f"so it is largely independent of the usual factors.")

    # 5. mechanics and economics
    if mech.get("mean_turnover") is not None:
        parts.append(f"Turnover is {_fmt(mech.get('mean_turnover'), 3)} of "
                     f"rank per session with {_fmt(mech.get('autocorrelation_1d'), 2)} "
                     f"one-day rank autocorrelation.")
    if bt.get("cagr_pct") is not None:
        parts.append(f"Under the canonical construction it returns "
                     f"{_fmt(bt.get('cagr_pct'), 2)}% a year at "
                     f"{_fmt(bt.get('mean_exposure_pct'), 0)}% exposure, "
                     f"Sharpe {_fmt(bt.get('sharpe'), 2)}, after costs.")

    # 6. the honest caveat
    eff = ic.get("effective_n")
    if eff is not None and eff < 30:
        parts.append(f"Only {eff} non-overlapping blocks back this, so treat a "
                     f"marginal t as marginal.")

    parts.append(f"Classified {failure_class}.")
    if next_moves:
        acts = "; ".join(m.get("action", "") for m in next_moves[:3] if m.get("action"))
        if acts:
            parts.append(f"Suggested next: {acts}.")
    return " ".join(p for p in parts if p)
