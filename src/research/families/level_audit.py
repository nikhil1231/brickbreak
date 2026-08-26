"""A blind audit of what H057 actually measured.

WHY THIS EXISTS
H057 reported that levels do not interrupt the path more than matched fake
lines. A null result on a *representation* is only worth what the representation
is worth: if the events the machine scored are not the setups a trader means,
then the study answered a different question and its null says nothing about
price action.

Argument cannot settle that. This can. The bundle below draws one horizontal
line on each chart. Half the lines are real detector levels; half are the
`permuted_geometry` fakes the study compared them against — same distance from
the reference close, same width, same volatility scaling, drawn from a different
symbol's history. Nothing on the chart says which is which.

Two things then become measurable rather than arguable:

  * **Can a human separate the real levels from the controls?** If not, then the
    machine's object and the reviewer's object are indistinguishable on exactly
    the cases the study scored, and the null stands as an answer to the question
    that was actually asked. If yes, and comfortably above chance, then the
    controls are matched on the wrong things, the detectors are missing what a
    human sees, and H057's null is about the wrong object. That would be a real
    finding and it would say precisely what to fix.
  * **Are these tradable setups at all?** A reviewer who marks nearly every case
    "skip" is saying the candidate population is not the setup population, which
    is a different and equally useful complaint.

The reviewer's own answers are the data. Chance is 50% by construction because
the deck is balanced, so this needs no model of what a good guess looks like.

WHAT IS HIDDEN AND WHEN
Truth lives only in `cases_private.jsonl` and in a `reveal` block that the
interface refuses to serve until the reviewer has finalised a complete pass.
Charts carry no symbol, no date, and rebased prices. The post-decision path is
never drawn — the chart ends exactly at the decision bar, so a reviewer cannot
read the answer off the future.

This spends no new sample. H057's path exposure is already logged and its result
published; this re-renders cases from that same read.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from . import level_reaction
from ...research_data.pipelines import levels as levels_pipeline


class ReviewBuildError(RuntimeError):
    pass


CHART_WIDTH, CHART_HEIGHT = 960, 520
HISTORY_BARS = 140

REVIEW_SCHEMA: dict[str, Any] = {
    "review_id": "h057-level-audit",
    "title": "Real level or matched fake?",
    "description": (
        "Each chart shows one horizontal line. Half the lines were drawn from "
        "this instrument's own history; half are controls placed at the same "
        "distance and width, taken from a different instrument. Decide which, "
        "and whether the setup is one you would trade."),
    "case_label": "chart",
    "instructions": (
        "Look only at the chart. It ends exactly at the decision bar; there is "
        "no future information anywhere in the case, and the instrument and "
        "date are removed.\n\n"
        "For each chart decide two independent things.\n\n"
        "First, is the drawn line a real level from this instrument's own "
        "history, or a control placed at a matched distance from somewhere "
        "else? Controls are matched on distance from the last close, on width, "
        "and on volatility, so distance alone will not tell you. What can tell "
        "you is whether the bars to the left actually did anything at that "
        "price.\n\n"
        "Second, and separately, would you trade a reaction here? Answer as you "
        "would in your own book, not as a guess about the algorithm. Marking "
        "most cases 'skip' is a legitimate and informative answer.\n\n"
        "The deck is balanced, so guessing scores 50%. Do not skip awkward "
        "cases; complete every one."),
    "guide": {
        "heading": "What this is testing",
        "summary": (
            "H057 measured whether price turns back at real levels more often "
            "than at these exact controls, and found it does not. That result "
            "only means something if these lines are the object you have in "
            "mind. If you cannot tell real from control, they are. If you can, "
            "the study measured the wrong thing and this says so."),
        "steps": [
            {"title": "1. Read the left side",
             "body": "A real level should have history at it: prior turns, a "
                     "consolidation edge, a gap it filled. A control has only "
                     "the distance right."},
            {"title": "2. Ignore how close it is",
             "body": "Distance from the last close is matched between the two "
                     "decks by construction and carries no information."},
            {"title": "3. Judge the trade separately",
             "body": "Whether you would take it is a different question from "
                     "whether the line is real. Answer both honestly, even "
                     "when they disagree."},
        ],
    },
    "fields": [
        {"name": "line_is_real", "label": "Is the drawn line a real level?",
         "description": ("Real means drawn from this instrument's own history. "
                         "Control means placed at a matched distance and width "
                         "from a different instrument."),
         "type": "choice", "required": True,
         "options": [
             {"value": "real", "label": "Real"},
             {"value": "fake", "label": "Control"},
         ]},
        {"name": "line_confidence", "label": "Confidence in that call",
         "type": "scale", "min": 0, "max": 1, "step": 0.05, "required": True},
        {"name": "would_trade", "label": "Would you trade a reaction here?",
         "description": ("Answer for your own book. Skipping most cases is a "
                         "legitimate and informative answer."),
         "type": "choice", "required": True,
         "options": [
             {"value": "long", "label": "Long"},
             {"value": "short", "label": "Short"},
             {"value": "skip", "label": "Skip"},
         ]},
        {"name": "notes", "label": "What made you decide",
         "description": "Only what is visible. Do not infer identity or date.",
         "type": "text", "max_length": 400, "required": False},
    ],
}

ANNOTATION_COLUMNS = (
    "case_id", "annotator", "annotator_kind", "provider", "model",
    "prompt_hash", "line_is_real", "line_confidence", "would_trade", "notes",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _render(bars: pd.DataFrame, level_low: float, level_high: float) -> bytes:
    """Candles ending at the decision bar, with one level band drawn.

    Prices are rebased so the last close is 100. That removes the instrument's
    identity without distorting any shape a reviewer would use, and it makes the
    real and control decks visually indistinguishable in every respect except
    the one being tested.
    """
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), "#0b1020")
    draw = ImageDraw.Draw(image)
    left, right, top, price_bottom = 48, CHART_WIDTH - 18, 20, int(CHART_HEIGHT * 0.78)
    volume_top, bottom = price_bottom + 12, CHART_HEIGHT - 22

    low = min(float(bars["low"].min()), level_low)
    high = max(float(bars["high"].max()), level_high)
    padding = max((high - low) * 0.06, 1e-6)
    low, high = low - padding, high + padding

    def y_price(value: float) -> int:
        return int(price_bottom - (value - low) / max(high - low, 1e-9)
                   * (price_bottom - top))

    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = int(top + fraction * (price_bottom - top))
        draw.line((left, y, right, y), fill="#212b42", width=1)

    count = len(bars)
    step = (right - left) / max(count, 1)
    candle = max(1, min(6, int(step * 0.55)))
    max_volume = max(float(bars["volume"].max()), 1.0)

    # The level is drawn first so candles sit on top of it and a reviewer can
    # see exactly which bars touched it.
    draw.rectangle((left, y_price(level_high), right, y_price(level_low)),
                   fill="#3a3320", outline="#ffd166", width=1)

    for index, row in enumerate(bars.itertuples(index=False)):
        x = int(left + (index + 0.5) * step)
        colour = "#42d392" if row.close >= row.open else "#ff6b6b"
        draw.line((x, y_price(row.high), x, y_price(row.low)), fill=colour, width=1)
        open_y, close_y = y_price(row.open), y_price(row.close)
        draw.rectangle((x - candle, min(open_y, close_y), x + candle,
                        max(max(open_y, close_y), min(open_y, close_y) + 1)),
                       fill=colour)
        height = int((bottom - volume_top) * float(row.volume) / max_volume)
        draw.rectangle((x - candle, bottom - height, x + candle, bottom),
                       fill=colour)

    draw.line((left, price_bottom, right, price_bottom), fill="#7080a0", width=1)
    draw.line((left, bottom, right, bottom), fill="#7080a0", width=1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def collect_cases(five_minute_bars: pd.DataFrame,
                  *, detectors: tuple[str, ...] | None = None,
                  seed: int = 20260826) -> pd.DataFrame:
    """Approach events for the real book and its permuted-geometry control.

    This is the same code path the study used — `levels.DETECTORS`,
    `find_approaches`, `build_pseudo_book` — so the audited cases are the scored
    cases and not a re-creation of them.
    """
    cfg = level_reaction.ReactionConfig(pseudo_per_real=1, seed=seed)
    level_cfg = levels_pipeline.LevelConfig()
    names = detectors or tuple(levels_pipeline.DETECTORS)

    hourly = levels_pipeline.resample_hourly(five_minute_bars)
    decisions = hourly.loc[hourly["complete"]].copy()
    reference = level_reaction._reference_frame(five_minute_bars, level_cfg)

    frames: list[pd.DataFrame] = []
    for name in names:
        book = levels_pipeline.DETECTORS[name](five_minute_bars, level_cfg)
        if book.empty:
            continue
        bounds = book.set_index("level_id")[["lower", "upper"]]
        real = level_reaction.find_approaches(
            decisions, book, reference, cfg, "real")
        fake_book = level_reaction.build_pseudo_book(
            book, reference, "permuted_geometry", cfg)
        fake = level_reaction.find_approaches(
            decisions, fake_book, reference, cfg, "permuted_geometry")
        fake_bounds = fake_book.set_index("level_id")[["lower", "upper"]]
        for events, source in ((real, bounds), (fake, fake_bounds)):
            if events.empty:
                continue
            joined = events.join(source, on="level_id")
            joined["detector"] = name
            frames.append(joined)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def freeze_review_bundle(cases: pd.DataFrame, hourly_bars: pd.DataFrame,
                         five_minute_bars: pd.DataFrame, output: Path,
                         *, n_cases: int = 60, seed: int = 20260826) -> dict[str, Any]:
    """Freeze a balanced, blind real-versus-control deck.

    The deck is balanced by construction so that chance is exactly 50% and the
    reviewer's score needs no reference distribution. Real cases are spread
    across detectors so that one detector's levels cannot carry the whole test.
    """
    if output.exists():
        raise ReviewBuildError(f"review bundle already exists: {output}")
    if cases.empty:
        raise ReviewBuildError("no approach events to review")

    rng = np.random.default_rng(seed)
    half = n_cases // 2
    real_pool = cases.loc[cases["book"] == "real"]
    fake_pool = cases.loc[cases["book"] != "real"]
    if len(real_pool) < half or len(fake_pool) < half:
        raise ReviewBuildError(
            f"need {half} of each deck, have {len(real_pool)} real "
            f"and {len(fake_pool)} control")

    per_detector = max(1, half // max(real_pool["detector"].nunique(), 1))
    picked: list[pd.DataFrame] = []
    for _, group in real_pool.groupby("detector", sort=True):
        take = min(per_detector, len(group))
        picked.append(group.sample(take, random_state=int(rng.integers(1 << 31))))
    real_selected = pd.concat(picked, ignore_index=True)
    if len(real_selected) > half:
        real_selected = real_selected.sample(
            half, random_state=int(rng.integers(1 << 31)))
    elif len(real_selected) < half:
        remainder = real_pool.drop(index=real_selected.index, errors="ignore")
        real_selected = pd.concat([
            real_selected,
            remainder.sample(half - len(real_selected),
                             random_state=int(rng.integers(1 << 31)))],
            ignore_index=True)
    fake_selected = fake_pool.sample(
        half, random_state=int(rng.integers(1 << 31)))

    deck = pd.concat([real_selected, fake_selected], ignore_index=True)
    deck = deck.sample(frac=1.0, random_state=int(rng.integers(1 << 31))) \
        .reset_index(drop=True)

    # The reveal carries what happened next. It is computed here so the
    # reviewer can see, after freezing, whether the case they judged tradable
    # actually turned -- but it never reaches the interface before then.
    path = levels_pipeline._normalise_bars(five_minute_bars)
    scored = level_reaction.race_barriers(deck, path, 0.50, 24)

    output.mkdir(parents=True, exist_ok=False)
    charts = output / "charts"
    charts.mkdir()

    hourly = hourly_bars.sort_values(["symbol", "bar_end"], kind="stable")
    grouped = {symbol: group.reset_index(drop=True)
               for symbol, group in hourly.groupby("symbol", sort=False)}

    records: list[dict[str, Any]] = []
    failures = 0
    for index, row in scored.iterrows():
        case_id = f"H057R_{index:03d}"
        frame = grouped.get(str(row["symbol"]))
        record: dict[str, Any] = {"case_id": case_id, "case_status": "ready"}
        if frame is None:
            failures += 1
            records.append({**record, "case_status": "source_failure"})
            continue
        history = frame.loc[
            pd.to_datetime(frame["bar_end"]) <= pd.Timestamp(row["approach_at"])]
        history = history.tail(HISTORY_BARS)
        if len(history) < 30:
            failures += 1
            records.append({**record, "case_status": "source_failure"})
            continue

        base = float(history["close"].iloc[-1])
        if not np.isfinite(base) or base <= 0:
            failures += 1
            records.append({**record, "case_status": "source_failure"})
            continue
        scale = 100.0 / base
        rebased = history.assign(
            open=history["open"] * scale, high=history["high"] * scale,
            low=history["low"] * scale, close=history["close"] * scale)
        level_low = float(row["lower"]) * scale
        level_high = float(row["upper"]) * scale
        chart = _render(rebased, level_low, level_high)
        (charts / f"{case_id}.png").write_bytes(chart)

        sidecar = {
            "bars_shown": int(len(rebased)),
            "last_close_rebased": round(float(rebased["close"].iloc[-1]), 4),
            "level_low_rebased": round(level_low, 4),
            "level_high_rebased": round(level_high, 4),
            "atr_rebased": round(float(row["atr"]) * scale, 4),
            "level_distance_atr": round(float(row["distance_atr"]), 3),
            "approached_from": str(row["approach_from"]),
        }
        case_hash = hashlib.sha256(
            (_canonical(sidecar) + hashlib.sha256(chart).hexdigest()).encode()
        ).hexdigest()[:16]
        records.append({
            **record,
            "case_hash": case_hash,
            "chart_sha256": hashlib.sha256(chart).hexdigest(),
            "sidecar": sidecar,
            # Served only after the reviewer finalises a complete pass.
            "reveal": {
                "line_was": "real" if row["book"] == "real" else "fake",
                "control_kind": (None if row["book"] == "real"
                                 else str(row["book"])),
                "detector": str(row["detector"]),
                "barrier_outcome_0.50atr_24bars": str(row["outcome"]),
            },
            "symbol_private": str(row["symbol"]),
            "decision_at_private": pd.Timestamp(row["approach_at"]).isoformat(),
        })

    (output / "cases_private.jsonl").write_text(
        "".join(_canonical(record) + "\n" for record in records))
    public = [{key: value for key, value in record.items()
               if key not in ("symbol_private", "decision_at_private")}
              for record in records]
    (output / "cases.jsonl").write_text(
        "".join(_canonical(record) + "\n" for record in public))
    pd.DataFrame(columns=list(ANNOTATION_COLUMNS)).to_csv(
        output / "annotations.csv", index=False)
    # The instructions are this study's prompt: they are what every reviewer,
    # human or model, is answering. Hashing them is what makes "the same pass"
    # a checkable claim rather than an assertion.
    prompt = REVIEW_SCHEMA["instructions"]
    (output / "annotation_prompt.txt").write_text(prompt)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    ready = [record for record in records if record["case_status"] == "ready"]
    real_count = sum(1 for record in ready
                     if record.get("reveal", {}).get("line_was") == "real")
    manifest = {
        "schema_version": "h057_level_audit.v1",
        "outcome_accessed": False,
        "hypothesis": "H057",
        "purpose": (
            "Audit whether the objects H057 scored are the objects a trader "
            "means by a level. Balanced blind deck; chance is 50%."),
        "seed": seed,
        "requested_cases": n_cases,
        "ready_cases": len(ready),
        "source_failures": failures,
        "real_cases": real_count,
        "control_cases": len(ready) - real_count,
        "history_bars": HISTORY_BARS,
        "decision_timeframe": "completed 60-minute bars",
        "case_set_hash": hashlib.sha256(
            "".join(record.get("case_hash", "FAILED") for record in records)
            .encode()).hexdigest(),
        "annotation_columns": list(ANNOTATION_COLUMNS),
        "annotation_prompt_hash": prompt_hash,
        "review_schema": REVIEW_SCHEMA,
        "spends_new_sample": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def score_pass(bundle: Path, annotator: str) -> dict[str, Any]:
    """Score a finalised human pass: can the reviewer beat a coin?

    Reports the discrimination rate with a binomial interval, the split by deck,
    and the take rate. A reviewer at chance means the machine's levels and the
    controls are the same object to a human eye, which is what makes H057's null
    an answer to the intended question rather than to a different one.
    """
    # Read with the stdlib rather than pandas on purpose. `research_data` is the
    # only door for *market* data; this is a review artifact this module froze
    # itself, and routing it through the data package would misrepresent it as
    # market data. The stdlib reader keeps that distinction visible.
    with (bundle / "annotations.csv").open(newline="") as handle:
        table = pd.DataFrame(list(csv.DictReader(handle)))
    if table.empty:
        raise ReviewBuildError("no finalised annotations in this bundle")
    cases = {json.loads(line)["case_id"]: json.loads(line)
             for line in (bundle / "cases_private.jsonl").read_text().splitlines()
             if line.strip()}
    rows = table.loc[table["annotator"].astype(str) == annotator]
    if rows.empty:
        raise ReviewBuildError(f"no finalised pass for annotator {annotator!r}")

    truth, guess, trade = [], [], []
    for _, row in rows.iterrows():
        record = cases.get(str(row["case_id"]))
        if not record or record.get("case_status") != "ready":
            continue
        truth.append(record["reveal"]["line_was"])
        guess.append(str(row["line_is_real"]))
        trade.append(str(row["would_trade"]))
    if not truth:
        return {"scored_cases": 0}

    truth_array = np.array(truth)
    guess_array = np.array(guess)
    correct = truth_array == guess_array
    count = len(correct)
    rate = float(correct.mean())
    error = float(np.sqrt(max(rate * (1 - rate), 1e-12) / count))
    return {
        "scored_cases": count,
        "discrimination_rate": round(rate, 4),
        "std_error": round(error, 4),
        "z_vs_chance": round((rate - 0.5) / error, 3) if error > 0 else None,
        "accuracy_on_real": round(
            float(correct[truth_array == "real"].mean()), 4)
            if (truth_array == "real").any() else None,
        "accuracy_on_controls": round(
            float(correct[truth_array == "fake"].mean()), 4)
            if (truth_array == "fake").any() else None,
        "take_rate": round(float((np.array(trade) != "skip").mean()), 4),
        "take_rate_on_real": round(
            float((np.array(trade)[truth_array == "real"] != "skip").mean()), 4)
            if (truth_array == "real").any() else None,
        "take_rate_on_controls": round(
            float((np.array(trade)[truth_array == "fake"] != "skip").mean()), 4)
            if (truth_array == "fake").any() else None,
        "interpretation": (
            "A discrimination rate near 0.5 means the reviewer cannot separate "
            "H057's real levels from its matched controls, so the study scored "
            "the object the reviewer has in mind. A rate materially above 0.5 "
            "means the controls miss something a human uses, and H057's null "
            "is about the wrong object."),
    }


__all__ = [
    "ANNOTATION_COLUMNS", "REVIEW_SCHEMA", "ReviewBuildError", "collect_cases",
    "freeze_review_bundle", "score_pass",
]
