"""H058 — does the owner's own eye select anything, and is he consistent?

WHY THIS EXISTS
H057 rejected level geometry, and its blind audit then showed why that
rejection is narrower than it looks: the reviewer could not separate real
levels from matched controls (0.533, interval covering chance), and he would
have traded only 16.7% of the deck — the same 16.7% on both halves. So the
study measured an object he recognises but a population he would never touch.
Its fourth limitation, that it averages over every approach and cannot see a
selected subset, stopped being a caveat and became the only live question in
the programme.

This family asks that question the one way it can be asked honestly: let the
reviewer define the population by marking his own setups on a frozen deck, and
compare what he took against what he passed over on the same sessions.

STAGE 0, WHICH IS ALL THIS MODULE DOES
Before spending five hours of a person's attention and the last untouched
partition, two things are worth knowing, and neither needs a single outcome:

  * **Does he agree with himself?** Thirty of the cases below are the same
    decision shown twice, far apart in the deck. If test-retest agreement on
    take/skip is near chance, no downstream contrast can carry information and
    the programme ends here for the price of one evening. PA7 already recorded
    a composite kappa of 0.087 between his level markup and the machine's, so
    this is a live risk and not a formality.
  * **What does the grind actually cost?** The take rate and the seconds spent
    per chart are what turn the Stage 2 sizing table from an assumption into a
    measurement. At 17% takes and 5s per skip a 0.20R test costs about five
    hours; at 35% it costs half that. Guessing which is a bad way to commit an
    evening.

WHAT IS AND IS NOT SPENT
Nothing. Charts end at the decision bar, no forward bar is read, loaded or
rendered, and the bundle physically cannot contain one. Stage 0 draws from
`validation` so that the 306 sessions of `test` stay untouched for the single
Stage 2 read, and so that any Stage 2 deck enrichment is fitted on one
partition and applied to another.

The duplicate pairs are rendered at different bar counts (140 and 128) ending
on the same decision bar. The decision is identical; the image is not. That
costs nothing and stops the retest from measuring picture recall instead of
judgement — though it cannot eliminate recall, so the agreement below is read
as an upper bound.

WHAT THE REVIEWER MARKS
Take or skip, and on a take three prices clicked straight onto the chart —
entry, stop, target — expressed as ATR offsets from the last close. Direction
is never asked: it is implied by whether the stop sits below the entry or above
it. That is one less field on every take, and it makes the pairing invariant
(`stop < entry < target`, or the exact reverse) checkable rather than trusted.
This lab has met a stop on the wrong side of an entry before.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from ...alpha_eval.guards import assert_no_forward_labels


class SetupGrindError(RuntimeError):
    pass


CHART_WIDTH, CHART_HEIGHT = 1100, 600
HISTORY_BARS = 140
REPEAT_HISTORY_BARS = 128
MIN_HISTORY_BARS = 90
# A repeat sits at least this many positions away from its original. The deck
# is 150 long, so this keeps every pair on opposite sides of a sitting.
MIN_REPEAT_GAP = 60

# Registered in HYPOTHESES.md before the reviewer sees a chart. Stage 0 does not
# use them -- it reads no outcome -- but they are frozen here so that the Stage 2
# resolver cannot be authored after the marks are in.
EXECUTION_RULES: dict[str, Any] = {
    "decision_at": "close of session D, on completed daily bars",
    "entry_trigger": (
        "the clicked entry level, live for 3 sessions from D+1. An entry above "
        "the last close triggers on high >= entry (breakout); one below "
        "triggers on low <= entry (pullback). No trigger in 3 sessions is a "
        "no-fill and is recorded, not dropped silently."),
    "entry_window_sessions": 3,
    "max_hold_sessions": 15,
    "exit": (
        "first of: stop touched, target touched, or the close of the 15th "
        "session after fill. Stop and target are checked against the session "
        "high/low; when a single session touches both, the stop is taken."),
    "instrument": "NSE stock futures, near expiry, rolled at 3 days to expiry",
    "cost_bps_round_trip": 10.0,
    "outcome": "R multiple, net of costs, where 1R is entry minus stop",
    # 3 + 15 = 18 sessions, inside split_v1's max_horizon of 20. A longer hold
    # would cross a purge boundary the split was never purged for.
    "horizon_sessions": 18,
}


# ---------------------------------------------------------------------------
# Stage 2. Everything below is registered before the deck exists and before any
# outcome is read. It is here rather than in a notebook so that the statistic,
# the control, the bar and the split list are one artefact with one git
# timestamp, and so that a resolver written later cannot quietly disagree with
# what was promised.
# ---------------------------------------------------------------------------

ANALYSIS_PLAN: dict[str, Any] = {
    "primary": {
        "name": "selection_value",
        "statistic": (
            "For each take, draw a control at random from the reviewer's own "
            "skips in the same session and apply the take's exact entry, stop "
            "and target offsets and its direction to that control. Resolve both "
            "under EXECUTION_RULES. The statistic is the mean paired difference "
            "in R, take minus matched skip."),
        "why_this_control": (
            "His skips are the only control that is matched on session, "
            "universe, rendering, reviewer and moment of judgement, and it "
            "costs nothing to collect. Applying the take's own geometry to the "
            "control holds entry, stop, target and direction fixed, so the "
            "difference is attributable to which chart he chose and to nothing "
            "else. This is the same pairing logic H057 used, with his pick as "
            "the real object and his own skip as the control."),
        "independent_unit": "session, clustered",
        "bar": {"min_paired_difference_r": 0.20, "min_clustered_t": 2.5},
    },
    "secondary_tradability": {
        "name": "net_payoff",
        "statistic": ("Mean R on takes under the reviewer's own geometry, net "
                      "of a 10 bps futures round trip."),
        "bar": {"min_mean_r": 0.20},
        "note": ("Selection value and tradability can disagree. A positive "
                 "primary with a negative secondary means his eye works and "
                 "his exits do not, which is a different project, not this one "
                 "passing."),
    },
    "secondary_execution": {
        "name": "markup_value",
        "statistic": (
            "On takes only, mean R under his drawn geometry minus mean R under "
            "a fixed mechanical geometry (entry at the decision close, stop at "
            "the median Stage 0 distance of 0.88 ATR, target at 2.45R, same "
            "direction). Answers whether drawing the trade adds anything over "
            "picking the chart."),
        "bar": None,
        "note": "Reported, not gated. It cannot fail the hypothesis.",
    },
    # Declared now so that no cut point can be chosen after the answer is
    # visible. Continuous variables split at the median OF THE STAGE 2 TAKES,
    # which is a rule rather than a threshold and so has nothing to tune.
    "splits": [
        {"name": "direction", "cut": "long vs short",
         "why": ("35:7 long in Stage 0. If the edge lives only in longs it may "
                 "be market beta wearing a costume.")},
        {"name": "trend_state", "cut": "close above vs below its 100-day SMA",
         "why": ("Pullback-in-uptrend and bottom-fishing are different trades. "
                 "This lab has twice found trend context flips a sign.")},
        {"name": "volatility", "cut": "median split on ATR as a % of price",
         "why": ("Stops are sized in ATR, so the same 1R is a much wider price "
                 "move in a volatile name.")},
        {"name": "dist_52w_high", "cut": "median split",
         "why": ("Breakout against reversion, and the exact variable H024 "
                 "reversed sign on.")},
        {"name": "reward_risk", "cut": "median split on the drawn reward:risk",
         "why": "Does he get paid more when he asks for more, or is a wide target a wish?",
         },
        {"name": "stop_distance", "cut": "median split on the drawn stop in ATR",
         "why": ("Separates a wrong read from a right read stopped out too "
                 "tight -- scrapping the idea against widening the stop.")},
        {"name": "conviction", "cut": "median split, as for the continuous four",
         "amended": "2026-08-28, before any outcome was read; see AMENDMENTS",
         "why": ("Stage 0's absolute scale failed 12/29/1. If the reworded "
                 "relative scale carries anything, the reproducible core is "
                 "where the edge concentrates and the dilution reverses.")},
    ],
    "multiplicity": {
        "rule": ("The primary is judged alone against its own bar. The seven "
                 "splits are judged together under Benjamini-Hochberg at "
                 "q = 0.10, and every split is reported with its estimate and "
                 "interval whether or not it survives."),
        "no_promotion_from_splits": (
            "A split that survives BH is a direction for a successor "
            "hypothesis, never a tradable claim on its own. The sample was "
            "sized for the primary."),
    },
    "power_stated_in_advance": {
        "note": ("At ~385 takes and an assumed 1.4R dispersion, a median split "
                 "puts ~192 per cell and the difference between cells carries a "
                 "standard error near 0.14R, so a gap under about 0.4R will "
                 "read as inconclusive. The unbalanced splits -- direction and "
                 "trend state -- are weaker still. Splits reading "
                 "'inconclusive' is the expected outcome and is not a defect."),
    },
    "consequence_of_failure": (
        "If the primary misses its bar, discretionary price action is retired "
        "as this lab's candidate for edge. The question will have been asked "
        "with the reviewer defining the population, on a partition never read "
        "before, against a control matched on everything but the choice "
        "itself. There is no cheaper or fairer version of it left to run."),
}

# Amendments are recorded here and written into the bundle as their own file.
# The frozen manifest is never rewritten: the original registration has to stay
# provable, so the delta is what gets published, not a quietly edited past.
AMENDMENTS: list[dict[str, Any]] = [
    {
        "date": "2026-08-28",
        "target": "splits.conviction",
        "from": "3 against 1-2",
        "to": "median split of the Stage 2 takes",
        "outcome_read_before_this": False,
        "evidence": ("At 406 of 1,685 charts the reworded scale had returned "
                     "29 ones, 58 twos and zero threes across 87 takes. The "
                     "registered cut would have been an empty cell."),
        "why_this_is_admissible": (
            "The change is decided on the distribution of a covariate the "
            "reviewer produces, with no outcome read and none readable -- the "
            "resolver has not been run. It substitutes the median rule already "
            "registered for the four continuous splits rather than inventing a "
            "new threshold, so there is still nothing to tune. Re-wording the "
            "scale mid-pass was rejected instead: it would change the prompt "
            "hash and split the pass into two different questions."),
        "what_it_costs": (
            "The split is now 'weaker than my median take' against 'at or "
            "above it', which is a softer contrast than the intended top-rank "
            "cut and correspondingly less likely to isolate a reproducible "
            "core."),
    },
]


REVIEW_SCHEMA: dict[str, Any] = {
    "review_id": "h058-setup-grind-stage0",
    "title": "Mark your own setups",
    "description": (
        "Daily charts ending at the decision bar. Mark the ones you would "
        "actually trade and place entry, stop and target on them. Most charts "
        "are nothing; saying so quickly is the point."),
    "case_label": "chart",
    # The deliberative form beside this one is right for sixty cases that each
    # deserve a paragraph, and wrong for a hundred and fifty where how fast the
    # no's go by is itself the measurement.
    "ui_mode": "grind",
    "instructions": (
        "Each chart is 140 daily bars of one instrument, ending at the close "
        "of the decision session. The name and the date are removed and prices "
        "are rebased, so nothing on the chart can tell you what it is. There "
        "is no future bar anywhere in this bundle.\n\n"
        "For each chart, one question first: is this a setup you would put "
        "money on, sized for your own book, in stock futures, held for days "
        "rather than weeks? Press J for no and F for yes. Most charts are a "
        "no. Going quickly on the no's is not carelessness -- it is the "
        "measurement.\n\n"
        "On a yes, click three levels straight onto the chart: entry, then "
        "stop, then target. Direction is taken from where you put the stop, so "
        "a stop below the entry is a long and a stop above it is a short. Then "
        "press 1, 2 or 3 for conviction and the deck moves on.\n\n"
        "Do not go back and tidy earlier answers. An inconsistent pass is a "
        "result, and a groomed one is not data. Some charts will feel "
        "familiar; mark them as you see them now rather than trying to "
        "remember what you did before."),
    "guide": {
        "heading": "What this is testing",
        "summary": (
            "The blind audit found you would have traded 16.7% of H057's "
            "charts, and the same 16.7% of its controls -- so that study "
            "measured a population you would never trade. This one lets you "
            "define the population instead. Before it spends the last clean "
            "partition, it checks the two things that would make the full "
            "grind pointless: whether you agree with yourself on a repeated "
            "chart, and what the grind actually costs per data point."),
        "steps": [
            {"title": "1. Fast on the no's",
             "body": "Four or five seconds is the target. If you are "
                     "deliberating, it is a no -- a setup you have to talk "
                     "yourself into is not the population being tested."},
            {"title": "2. Three clicks on the yes's",
             "body": "Entry, stop, target, in that order, clicked on the "
                     "chart. Place them where you would really put them, not "
                     "where they make the trade look good."},
            {"title": "3. Do not groom the pass",
             "body": "Repeats are in the deck on purpose and they are what "
                     "makes this worth running. Answering them from memory "
                     "destroys the only number Stage 0 exists to produce."},
        ],
    },
    "fields": [
        {"name": "action", "label": "Is this a setup you would trade?",
         "description": "F for yes, J for no. Most charts are a no.",
         "type": "choice", "required": True,
         "ui_control": "triage",
         "options": [
             {"value": "take", "label": "Take (F)"},
             {"value": "skip", "label": "Skip (J)"},
         ]},
        {"name": "entry_atr", "label": "Entry",
         "description": ("Click the chart. Measured in ATR from the last "
                         "close; above it is a breakout entry, below it a "
                         "pullback entry."),
         "type": "number", "min": -50, "max": 50, "step": 0.05,
         "ui_control": "chart_level_atr", "ui_order": 1,
         "required_when": {"action": "take"}},
        {"name": "stop_atr", "label": "Stop",
         "description": ("Where the idea is wrong. Below the entry makes this "
                         "a long, above it a short -- direction is not asked "
                         "separately."),
         "type": "number", "min": -50, "max": 50, "step": 0.05,
         "ui_control": "chart_level_atr", "ui_order": 2,
         "required_when": {"action": "take"}},
        {"name": "target_atr", "label": "Target",
         "description": "Where you would take it off, if it goes your way.",
         "type": "number", "min": -50, "max": 50, "step": 0.05,
         "ui_control": "chart_level_atr", "ui_order": 3,
         "required_when": {"action": "take"}},
        {"name": "conviction", "label": "Compared with your other takes",
         # Stage 0 used an absolute scale and got 12/29/1 back, because the
         # owner read "3" as confidence in the strategy -- which he does not
         # have -- rather than a ranking among his own picks. Asking only for a
         # ranking against himself is answerable by someone who doubts the whole
         # enterprise, which is the honest state to be in here.
         "description": ("1 at the weaker end · 2 typical for you · 3 one of "
                         "the better ones this session. Rank against your own "
                         "takes, not against whether the strategy works."),
         "type": "scale", "min": 1, "max": 3, "step": 1,
         "required_when": {"action": "take"}},
        {"name": "notes", "label": "Note (optional)",
         "description": "Only if something is worth saying. Never required.",
         "type": "text", "max_length": 300, "required": False},
        {"name": "seconds_elapsed", "label": "Seconds on this chart",
         "description": "Recorded automatically.",
         "type": "number", "min": 0, "max": 3600, "required": False,
         "ui_control": "timer"},
    ],
    "invariants": [
        {"when": {"action": "take"},
         "rule": "strictly_ordered",
         "fields": ["stop_atr", "entry_atr", "target_atr"],
         "either_direction": True,
         "message": ("Entry must sit between the stop and the target. A stop "
                     "on the far side of the entry is a pairing bug, not a "
                     "trade.")},
    ],
}


def _stage2_schema() -> dict[str, Any]:
    """Stage 2 asks the same question with the same keys and a different deck.

    Derived from the Stage 0 schema rather than copied so that the fields, the
    invariant and the grind layout cannot drift apart between the two passes --
    a reviewer answering a differently worded form is answering a different
    question, and the two passes would not be comparable.
    """
    schema = json.loads(json.dumps(REVIEW_SCHEMA))
    schema.update({
        "review_id": "h058-setup-grind-stage2",
        "title": "Mark your own setups — the real run",
        "description": (
            "The same job as the practice deck, on charts that have never been "
            "looked at. This is the one that gets scored."),
        "instructions": (
            "Same as before: J for no, F for yes, then click entry, stop and "
            "target and press 1, 2 or 3.\n\n"
            "Two things are different. These charts come from a partition "
            "nothing in this project has ever read, and they are scored "
            "against what actually happened afterwards, once, and never "
            "again.\n\n"
            "The conviction question has changed. It now asks only how a setup "
            "ranks against your *own other takes* -- weaker end, typical, or "
            "one of the better ones this session. It is not asking whether you "
            "believe the strategy works. Answer it as a ranking and it will be "
            "usable; answer it as confidence and it will be 12/29/1 again.\n\n"
            "This is long. Stop when you get tired -- the deck is resumable and "
            "a tired pass is worse than a short one. Do not go back and tidy "
            "earlier answers."),
        "guide": {
            "heading": "What this run decides",
            "summary": (
                "Every take is paired with one of your own skips from the same "
                "session, traded with the identical entry, stop, target and "
                "direction. So the only thing separating the two is which chart "
                "you picked. If your takes beat your matched skips by 0.20R "
                "with a session-clustered t of 2.5, the eye is real. If they do "
                "not, discretionary price action is retired and the question "
                "has been asked fairly."),
            "steps": [
                {"title": "1. Fast on the no's",
                 "body": "Three seconds was your Stage 0 pace and it was fine. "
                         "The skips are not filler -- they are the control that "
                         "the whole result rests on."},
                {"title": "2. Rank against yourself",
                 "body": "Conviction now means better or worse than your other "
                         "takes. A 3 does not claim the strategy works."},
                {"title": "3. Stop when tired",
                 "body": "It is resumable and it is scored once. There is no "
                         "prize for finishing in one sitting."},
            ],
        },
    })
    return schema


STAGE2_REVIEW_SCHEMA: dict[str, Any] = _stage2_schema()

ANNOTATION_COLUMNS = (
    "case_id", "annotator", "annotator_kind", "provider", "model",
    "prompt_hash", "action", "entry_atr", "stop_atr", "target_atr",
    "conviction", "notes", "seconds_elapsed",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def assert_session_aligned(bars: pd.DataFrame, context: str = "chart bars") -> None:
    """Refuse a frame whose OHLC columns come from different sessions.

    The lab's as-of-open screening panel deliberately carries date D's opening
    print beside date D-1's high, low and close, because that is what a morning
    screener knows (`research_data.pipelines.asof`). Drawing those four numbers
    as one candle is silently wrong and puts the next session's opening print on
    a chart that is supposed to end at the decision bar. An open that sits
    outside its own bar's range is the cheapest possible tell, so it is checked
    rather than assumed.
    """
    frame = bars[["open", "high", "low"]].apply(pd.to_numeric, errors="coerce")
    inside = ((frame["open"] >= frame["low"]) & (frame["open"] <= frame["high"]))
    rate = float(inside.mean()) if len(frame) else 1.0
    if rate < 0.999:
        raise SetupGrindError(
            f"{context}: the open sits outside its own bar's range in "
            f"{1 - rate:.1%} of rows, so these columns are not one session's "
            "OHLC. Use corporate_actions.load_adjusted(), not the as-of panel.")


def true_range_atr(window: pd.DataFrame, periods: int = 14) -> float:
    """ATR over the visible window only, so it cannot import a future bar.

    Taking ATR from the screening panel instead would mean reasoning about
    which session that panel's row refers to, every time. Computing it from the
    bars already on the chart makes the answer causal by construction.
    """
    high = pd.to_numeric(window["high"], errors="coerce")
    low = pd.to_numeric(window["low"], errors="coerce")
    close = pd.to_numeric(window["close"], errors="coerce")
    previous = close.shift(1)
    ranges = pd.concat([high - low, (high - previous).abs(),
                        (low - previous).abs()], axis=1).max(axis=1)
    return float(ranges.tail(periods).mean())


def eligible_decisions(bars: pd.DataFrame, universe: pd.DataFrame,
                       partitions: pd.DataFrame,
                       *, partition: str = "validation") -> pd.DataFrame:
    """Symbol-sessions that can carry a fair chart, before anything is chosen.

    Deliberately broad. The whole point of Stage 0 is to measure the take rate
    on a population that has not been shaped to flatter it, so the only filters
    here are ones that would otherwise put a lie on the screen: F&O membership
    on that session, enough history to fill the window, and a live traded bar.
    """
    assert_no_forward_labels(bars, context="H058 Stage 0 deck")
    assert_session_aligned(bars, context="H058 Stage 0 deck")
    if "partition" not in partitions.columns:
        raise SetupGrindError(
            "partitions must come from splits.assign; a hand-written date "
            "range is how a holdout gets read twice")

    wanted = partitions.loc[
        partitions["partition"].astype(str) == partition, "date"]
    wanted = pd.to_datetime(pd.Series(wanted).drop_duplicates())

    frame = bars.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.loc[frame["date"].isin(set(wanted))]

    members = universe.rename(columns={"session": "date"})[["symbol", "date"]].copy()
    members["date"] = pd.to_datetime(members["date"])
    frame = frame.merge(members, on=["symbol", "date"], how="inner")

    # Require the history to sit *before this decision*, not merely somewhere
    # in the frame. A symbol-session near the start of the archive has plenty
    # of bars after it and none before, and selecting it only to reject it at
    # render time silently shrinks the deck and skews it late.
    ordered = bars[["symbol", "date"]].copy()
    ordered["date"] = pd.to_datetime(ordered["date"])
    ordered = ordered.sort_values(["symbol", "date"], kind="stable")
    ordered["prior_bars"] = ordered.groupby("symbol").cumcount()
    frame = frame.merge(ordered, on=["symbol", "date"], how="left")
    frame = frame.loc[frame["prior_bars"].ge(MIN_HISTORY_BARS)]

    ok = (
        pd.to_numeric(frame["close"], errors="coerce").gt(0)
        & pd.to_numeric(frame["volume"], errors="coerce").gt(0)
    )
    return frame.loc[ok, ["symbol", "date", "close"]].reset_index(drop=True)


def _window(history: pd.DataFrame, decision_at: pd.Timestamp,
            bars: int) -> pd.DataFrame:
    """The bars a reviewer may see, and not one more.

    Filtering on the decision timestamp here rather than trusting the caller is
    deliberate: three of this project's four lookaheads entered through code
    that assumed its input had already been cut.
    """
    frame = history.loc[pd.to_datetime(history["date"]) <= decision_at]
    return frame.sort_values("date", kind="stable").tail(bars).reset_index(
        drop=True)


def _axis(low: float, high: float) -> dict[str, float]:
    return {
        "width": CHART_WIDTH, "height": CHART_HEIGHT,
        "left": 52, "right": CHART_WIDTH - 18,
        "price_top": 20, "price_bottom": int(CHART_HEIGHT * 0.78),
        "price_low": round(low, 6), "price_high": round(high, 6),
    }


def _render(bars: pd.DataFrame) -> tuple[bytes, dict[str, float]]:
    """Daily candles ending at the decision bar, rebased so the last close is 100.

    Rebasing removes the instrument's identity without touching any shape a
    reviewer reads. The axis is returned rather than reconstructed in the
    browser: the reviewer places three prices by clicking this image, so the
    pixel-to-price map is part of the data, not a constant two files apart that
    someone will one day change on one side only.
    """
    image = Image.new("RGB", (CHART_WIDTH, CHART_HEIGHT), "#0b1020")
    draw = ImageDraw.Draw(image)
    low = float(bars["low"].min())
    high = float(bars["high"].max())
    padding = max((high - low) * 0.06, 1e-6)
    low, high = low - padding, high + padding
    axis = _axis(low, high)
    left, right = axis["left"], axis["right"]
    top, price_bottom = axis["price_top"], axis["price_bottom"]
    volume_top, bottom = price_bottom + 14, CHART_HEIGHT - 22

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
    return buffer.getvalue(), axis


def _clean_window(window: pd.DataFrame) -> str | None:
    """Reject a window that would show the reviewer something untrue."""
    if len(window) < MIN_HISTORY_BARS:
        return "insufficient_history"
    values = window[["open", "high", "low", "close", "volume"]].apply(
        pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        return "missing_bars"
    if (values["high"] < values["low"]).any() or (values["close"] <= 0).any():
        return "invalid_ohlc"
    if ((values["open"] < values["low"]) | (values["open"] > values["high"])).any():
        return "open_outside_bar"
    if (values["volume"] < 0).any():
        return "negative_volume"
    # An unadjusted split or bonus draws a cliff that no trader would read as
    # price action. The panel is adjusted, so this should never fire -- which
    # is why it is worth asserting rather than assuming.
    moves = values["close"].pct_change().abs().max(skipna=True)
    if pd.notna(moves) and float(moves) > 0.40:
        return "suspected_corporate_action"
    return None


def build_deck(decisions: pd.DataFrame, *, n_unique: int = 120,
               n_repeats: int = 50, max_per_symbol: int = 2,
               max_per_session: int | None = None,
               min_repeat_gap: int = MIN_REPEAT_GAP,
               seed: int = 20260827) -> pd.DataFrame:
    """Choose the decisions and lay out the order the reviewer meets them in.

    Sources are the first `n_repeats` slots and repeats live past
    `n_repeats + min_repeat_gap`, which makes the separation a property of the
    construction rather than something to check afterwards and hope for. The
    reviewer therefore meets a chart's second copy at least sixty decisions --
    in practice a different sitting -- after the first.
    """
    total = n_unique + n_repeats
    if n_repeats < 0:
        raise SetupGrindError("a deck cannot contain a negative number of repeats")
    if n_repeats and total < 2 * n_repeats + min_repeat_gap:
        raise SetupGrindError(
            f"a {total}-case deck cannot hold {n_repeats} repeats "
            f"{min_repeat_gap} apart; it needs at least "
            f"{2 * n_repeats + min_repeat_gap} cases")
    if len(decisions) < n_unique:
        raise SetupGrindError(
            f"need {n_unique} eligible decisions, have {len(decisions)}")

    rng = np.random.default_rng(seed)
    shuffled = decisions.sample(frac=1.0, random_state=int(
        rng.integers(1 << 31))).reset_index(drop=True)
    capped = shuffled.groupby("symbol", sort=False).head(max_per_symbol)
    if max_per_session is not None:
        # The independent unit is the session, and the paired contrast needs
        # several decisions inside one. Capping keeps a handful of sessions from
        # carrying the study while still leaving enough per session to pair in.
        capped = capped.groupby("date", sort=False).head(max_per_session)
    if len(capped) < n_unique:
        raise SetupGrindError(
            f"the per-symbol cap of {max_per_symbol} leaves {len(capped)} "
            f"decisions, and the deck needs {n_unique}")
    picked = capped.head(n_unique).reset_index(drop=True)

    repeat_slots = sorted(rng.choice(
        np.arange(n_repeats + min_repeat_gap, total),
        size=n_repeats, replace=False).tolist()) if n_repeats else []
    reserved = set(repeat_slots)
    original_slots = [slot for slot in range(total) if slot not in reserved]
    source_slots = original_slots[:n_repeats]

    layout: dict[int, dict[str, Any]] = {}
    for position, slot in enumerate(original_slots):
        layout[slot] = {"source_index": position, "repeat_of_slot": None}
    for repeat_slot, source_slot in zip(repeat_slots, source_slots):
        layout[repeat_slot] = {
            "source_index": layout[source_slot]["source_index"],
            "repeat_of_slot": source_slot,
        }

    rows = []
    for slot in range(total):
        entry = layout[slot]
        row = picked.iloc[entry["source_index"]].to_dict()
        row.update({
            "slot": slot,
            "is_repeat": entry["repeat_of_slot"] is not None,
            "repeat_of_slot": entry["repeat_of_slot"],
            "history_bars": (REPEAT_HISTORY_BARS if entry["repeat_of_slot"]
                             is not None else HISTORY_BARS),
        })
        rows.append(row)
    deck = pd.DataFrame(rows)

    repeats = deck.loc[deck["is_repeat"]]
    gaps = [int(slot) - int(source) for slot, source in
            zip(repeats["slot"], repeats["repeat_of_slot"])]
    if gaps and min(gaps) < min_repeat_gap:
        raise SetupGrindError(
            f"a repeat sits {min(gaps)} charts from its original, under the "
            f"{min_repeat_gap} required to keep this a retest and not a memory "
            "test")
    return deck


def freeze_stage0_bundle(deck: pd.DataFrame, bars: pd.DataFrame,
                         output: Path, *, stage: str = "stage_0",
                         partition: str = "validation") -> dict[str, Any]:
    """Write the frozen, outcome-free Stage 0 bundle.

    Every chart is rendered from bars at or before its own decision session.
    The linkage between a repeat and its original is written only to the
    private file: a reviewer who can see which charts are repeats is not
    producing a retest.
    """
    if output.exists():
        raise SetupGrindError(f"review bundle already exists: {output}")
    assert_no_forward_labels(bars, context="H058 Stage 0 bundle")
    assert_session_aligned(bars, context="H058 Stage 0 bundle")

    histories = {symbol: group.sort_values("date", kind="stable")
                 for symbol, group in bars.groupby("symbol", sort=False)}

    output.mkdir(parents=True, exist_ok=False)
    charts = output / "charts"
    charts.mkdir()

    records: list[dict[str, Any]] = []
    failures = 0
    for _, row in deck.sort_values("slot").iterrows():
        case_id = f"H058S0_{int(row['slot']):03d}"
        decision_at = pd.Timestamp(row["date"])
        history = histories.get(str(row["symbol"]))
        if history is None:
            failures += 1
            records.append({"case_id": case_id, "case_status": "source_failure",
                            "error": "no history for symbol"})
            continue
        window = _window(history, decision_at, int(row["history_bars"]))
        problem = _clean_window(window)
        if problem is not None:
            failures += 1
            records.append({"case_id": case_id, "case_status": "source_failure",
                            "error": problem})
            continue

        base = float(window["close"].iloc[-1])
        scale = 100.0 / base
        rebased = window.assign(
            open=window["open"] * scale, high=window["high"] * scale,
            low=window["low"] * scale, close=window["close"] * scale)
        # Computed from the bars on the chart, so it cannot reach past the
        # decision bar. The rebased close is exactly 100, so this is also the
        # ATR as a percentage of the last close. Checked before anything is
        # written, so a rejected case leaves no orphan chart behind.
        atr_rebased = true_range_atr(rebased)
        if not np.isfinite(atr_rebased) or atr_rebased <= 0:
            failures += 1
            records.append({"case_id": case_id, "case_status": "source_failure",
                            "error": "degenerate_atr"})
            continue
        chart, axis = _render(rebased)
        (charts / f"{case_id}.png").write_bytes(chart)

        sidecar = {
            "axis": axis,
            "last_close_rebased": 100.0,
            "atr_rebased": round(atr_rebased, 4),
            "visible_low_rebased": round(float(rebased["low"].min()), 4),
            "visible_high_rebased": round(float(rebased["high"].max()), 4),
        }
        case_hash = hashlib.sha256(
            (_canonical(sidecar) + hashlib.sha256(chart).hexdigest()).encode()
        ).hexdigest()[:16]
        records.append({
            "case_id": case_id,
            "case_status": "ready",
            "case_hash": case_hash,
            "chart_sha256": hashlib.sha256(chart).hexdigest(),
            "sidecar": sidecar,
            "symbol_private": str(row["symbol"]),
            "decision_at_private": decision_at.isoformat(),
            "is_repeat_private": bool(row["is_repeat"]),
            "repeat_of_slot_private": (None if pd.isna(row["repeat_of_slot"])
                                       else int(row["repeat_of_slot"])),
            "slot_private": int(row["slot"]),
        })

    (output / "cases_private.jsonl").write_text(
        "".join(_canonical(record) + "\n" for record in records))
    private_keys = {"symbol_private", "decision_at_private", "is_repeat_private",
                    "repeat_of_slot_private", "slot_private"}
    (output / "cases.jsonl").write_text("".join(
        _canonical({key: value for key, value in record.items()
                    if key not in private_keys}) + "\n"
        for record in records))
    pd.DataFrame(columns=list(ANNOTATION_COLUMNS)).to_csv(
        output / "annotations.csv", index=False)
    schema = STAGE2_REVIEW_SCHEMA if stage == "stage_2" else REVIEW_SCHEMA
    prompt = schema["instructions"]
    (output / "annotation_prompt.txt").write_text(prompt)

    ready = [record for record in records if record["case_status"] == "ready"]
    stage_2 = stage == "stage_2"
    manifest = {
        "schema_version": f"h058_setup_grind_{stage}.v1",
        # Stamped so the interface can order queues by recency instead of
        # inferring it from the review id, which is only chronological by
        # accident of the H0xx naming.
        "created": datetime.now(timezone.utc).isoformat(),
        "outcome_accessed": False,
        "hypothesis": "H058",
        "stage": ("stage_2_selection_value" if stage_2
                  else "stage_0_consistency_and_cost"),
        "purpose": (
            "Measure whether the reviewer's takes beat his own matched skips, "
            "and where. The single scored read of the `test` partition."
            if stage_2 else
            "Measure whether the reviewer's own take/skip judgement is "
            "reproducible on a repeated chart, and what a data point costs in "
            "minutes. Reads no outcome and spends no sample."),
        "partition": partition,
        "partition_note": (
            "The one scored read of `test`. 306 sessions over five quarters, "
            "never read by this programme; session-clustered inference is well "
            "supported and regime robustness rests on five blocks."
            if stage_2 else
            "Stage 0 deliberately avoids `test` so the 306 test sessions stay "
            "untouched for the single Stage 2 read, and so any Stage 2 deck "
            "enrichment is fitted on one partition and applied to another."),
        "requested_cases": int(len(deck)),
        "ready_cases": len(ready),
        "source_failures": failures,
        "repeat_pairs": int(deck["is_repeat"].sum()),
        "history_bars": HISTORY_BARS,
        "repeat_history_bars": REPEAT_HISTORY_BARS,
        "min_repeat_gap": MIN_REPEAT_GAP,
        "decision_timeframe": "completed daily bars",
        "execution_rules_registered_for_stage_2": EXECUTION_RULES,
        "acceptance_bar": (ANALYSIS_PLAN if stage_2 else STAGE0_BAR),
        "annotation_columns": list(ANNOTATION_COLUMNS),
        "annotation_prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
        "case_set_hash": hashlib.sha256(
            "".join(record.get("case_hash", "FAILED") for record in records
                    ).encode()).hexdigest(),
        "review_schema": (STAGE2_REVIEW_SCHEMA if stage_2 else REVIEW_SCHEMA),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# Fixed before the reviewer sees a chart, and frozen into the manifest. The
# thresholds are decision rules, not descriptions: a bar applied only when it is
# passed is not a bar.
STAGE0_BAR: dict[str, Any] = {
    "primary": "test_retest_kappa_take_skip",
    "stop": 0.20,
    "proceed_full": 0.40,
    "min_take_rate": 0.05,
    "max_take_rate": 0.60,
    "rule": (
        "Kappa below 0.20 ends the programme: a selection the reviewer cannot "
        "reproduce on the same chart two hours apart cannot be measured "
        "against outcomes, and no deck size fixes it. Kappa at or above 0.40 "
        "opens Stage 2 at the five-hour, 0.20R size. Between the two, Stage 2 "
        "opens only at the two-hour, 0.30R size, because a noisy selector "
        "needs a larger effect before the grind is worth it. Independently, a "
        "take rate under 0.05 makes the full grind unaffordable and one over "
        "0.60 means the reviewer is labelling rather than selecting; either "
        "sends the deck back to be redrawn rather than opening outcomes."),
    "not_a_gate": [
        "seconds per chart -- used only to size Stage 2",
        "geometry agreement on repeated takes -- reported, too few pairs to gate",
    ],
}

# Per-trade dispersion assumed when sizing Stage 2, in R. A hard stop with a
# roughly 2R target puts the standard deviation near 1.4R; it is stated here so
# the sizing table can be recomputed against the number actually observed.
ASSUMED_SIGMA_R = 1.4
_Z_SUM = 1.959964 + 0.841621  # two-sided 5%, 80% power


def _kappa(left: pd.Series, right: pd.Series) -> float | None:
    """Cohen's kappa for two binary passes over the same cases."""
    pair = pd.DataFrame({"a": left, "b": right}).dropna()
    if pair.empty:
        return None
    observed = float((pair["a"] == pair["b"]).mean())
    categories = sorted(set(pair["a"]) | set(pair["b"]))
    expected = sum(float((pair["a"] == value).mean())
                   * float((pair["b"] == value).mean()) for value in categories)
    if expected >= 1.0:
        # Both passes were constant and identical. Agreement is total and kappa
        # is undefined rather than perfect; saying so beats returning 1.0.
        return None
    return (observed - expected) / (1.0 - expected)


def _direction(row: pd.Series) -> str | None:
    entry, stop = row.get("entry_atr"), row.get("stop_atr")
    if pd.isna(entry) or pd.isna(stop):
        return None
    return "long" if float(stop) < float(entry) else "short"


def stage2_sizing(take_rate: float, seconds_per_skip: float,
                  seconds_per_take: float,
                  *, sigma_r: float = ASSUMED_SIGMA_R) -> list[dict[str, Any]]:
    """What each detectable edge would cost in charts and hours, as measured.

    This replaces the assumed take rate and pace in the pre-study sizing table
    with the reviewer's own, which is the entire reason Stage 0 exists.
    """
    if not 0.0 < take_rate <= 1.0:
        raise SetupGrindError("take rate must sit in (0, 1] to size a grind")
    rows = []
    for edge in (0.40, 0.30, 0.25, 0.20, 0.15):
        takes = int(np.ceil((_Z_SUM * sigma_r / edge) ** 2))
        charts = int(np.ceil(takes / take_rate))
        seconds = ((charts - takes) * seconds_per_skip
                   + takes * seconds_per_take)
        rows.append({
            "detectable_edge_r": edge,
            "takes_needed": takes,
            "charts_needed": charts,
            "hours": round(seconds / 3600.0, 2),
        })
    return rows


def stage0_report(annotations: pd.DataFrame, manifest: dict[str, Any],
                  private_cases: list[dict[str, Any]],
                  *, annotator: str) -> dict[str, Any]:
    """Score one frozen human pass. Reads no outcome and cannot.

    The verdict is computed from `STAGE0_BAR` as frozen in the manifest, not
    from the module constant, so that editing the bar after a pass is frozen
    changes nothing about how that pass is judged.
    """
    if manifest.get("outcome_accessed"):
        raise SetupGrindError("Stage 0 must not run against an opened bundle")
    frame = annotations.loc[
        annotations["annotator"].astype(str).eq(annotator)
        & annotations["annotator_kind"].astype(str).eq("human")].copy()
    if frame.empty:
        raise SetupGrindError(f"no frozen pass by {annotator}")
    expected = manifest.get("annotation_prompt_hash")
    # Passes frozen before the interface stamped the prompt hash carry an empty
    # one. That is unverifiable rather than wrong, so it is allowed and said out
    # loud in the report; a hash that is present and different is a different
    # test of the same cases and is refused.
    seen = {value for value in frame["prompt_hash"].astype(str) if value}
    unverified = bool((frame["prompt_hash"].astype(str) == "").any())
    if expected and seen - {str(expected)}:
        raise SetupGrindError(
            "the pass answers a prompt other than the frozen one; it is a "
            "different test of the same cases, not this one")

    frame["action"] = frame["action"].astype(str)
    frame = frame.set_index("case_id")
    # The take rate is counted over first showings only. A repeat is the same
    # decision seen twice, and counting it twice would both narrow the interval
    # dishonestly and drag the rate toward whatever the repeated cases were.
    originals = [record["case_id"] for record in private_cases
                 if not record.get("is_repeat_private")]
    first_showing = frame.loc[frame.index.isin(originals)]
    takes = first_showing["action"].eq("take")
    n = int(len(first_showing))
    take_count = int(takes.sum())
    take_rate = take_count / n if n else 0.0
    # Wilson interval: the normal approximation misbehaves badly at the low
    # take rates this deck is expected to produce.
    z = 1.959964
    centre = (take_count + z * z / 2) / (n + z * z) if n else 0.0
    spread = (z / (n + z * z)) * np.sqrt(
        take_count * (n - take_count) / n + z * z / 4) if n else 0.0

    # Pace, unlike the take rate, is measured over every chart the reviewer
    # actually sat in front of, repeats included.
    seconds = pd.to_numeric(frame.get("seconds_elapsed"), errors="coerce")
    all_takes = frame["action"].eq("take")
    skip_seconds = (float(seconds[~all_takes].median())
                    if (~all_takes).any() else float("nan"))
    take_seconds = (float(seconds[all_takes].median())
                    if all_takes.any() else float("nan"))

    lookup = {record["case_id"]: record for record in private_cases}
    slots = {record["slot_private"]: record["case_id"]
             for record in private_cases if "slot_private" in record}
    pairs = []
    for record in private_cases:
        if not record.get("is_repeat_private"):
            continue
        origin = slots.get(record.get("repeat_of_slot_private"))
        if origin is None or origin not in frame.index \
                or record["case_id"] not in frame.index:
            continue
        first, second = frame.loc[origin], frame.loc[record["case_id"]]
        pairs.append({
            "original_case_id": origin,
            "repeat_case_id": record["case_id"],
            "first_action": str(first["action"]),
            "second_action": str(second["action"]),
            "first_direction": _direction(first),
            "second_direction": _direction(second),
        })
    pair_frame = pd.DataFrame(pairs)
    kappa = None if pair_frame.empty else _kappa(
        pair_frame["first_action"], pair_frame["second_action"])
    both_taken = pair_frame.loc[
        pair_frame["first_action"].eq("take")
        & pair_frame["second_action"].eq("take")] if not pair_frame.empty \
        else pd.DataFrame()
    direction_agreement = (
        float((both_taken["first_direction"] == both_taken["second_direction"]).mean())
        if not both_taken.empty else None)

    violations = []
    for case_id, row in frame.loc[all_takes].iterrows():
        entry, stop, target = (row.get("entry_atr"), row.get("stop_atr"),
                               row.get("target_atr"))
        if any(pd.isna(value) for value in (entry, stop, target)):
            violations.append({"case_id": case_id, "problem": "incomplete_geometry"})
            continue
        entry, stop, target = float(entry), float(stop), float(target)
        if not (stop < entry < target or stop > entry > target):
            violations.append({"case_id": case_id, "problem": "entry_outside_stop_target"})

    bar = manifest.get("acceptance_bar", STAGE0_BAR)
    if kappa is None:
        verdict, reason = "inconclusive", "test-retest kappa is undefined"
    elif kappa < bar["stop"]:
        verdict, reason = "stop", (
            f"test-retest kappa {kappa:.2f} is below the registered stop of "
            f"{bar['stop']:.2f}")
    elif kappa >= bar["proceed_full"]:
        verdict, reason = "proceed_full", (
            f"test-retest kappa {kappa:.2f} clears {bar['proceed_full']:.2f}")
    else:
        verdict, reason = "proceed_reduced", (
            f"test-retest kappa {kappa:.2f} sits between the registered "
            f"{bar['stop']:.2f} and {bar['proceed_full']:.2f}")
    if verdict.startswith("proceed") and not (
            bar["min_take_rate"] <= take_rate <= bar["max_take_rate"]):
        verdict, reason = "redraw_deck", (
            f"take rate {take_rate:.1%} falls outside the registered "
            f"[{bar['min_take_rate']:.0%}, {bar['max_take_rate']:.0%}] band")

    sizing = None
    if take_rate > 0 and np.isfinite(skip_seconds) and np.isfinite(take_seconds):
        sizing = stage2_sizing(take_rate, skip_seconds, take_seconds)

    return {
        "stage": "H058_STAGE0",
        "outcome_accessed": False,
        "annotator": annotator,
        "case_set_hash": manifest.get("case_set_hash"),
        "prompt_hash": manifest.get("annotation_prompt_hash"),
        "prompt_hash_unverified": unverified,
        "cases_reviewed": int(len(frame)),
        "first_showings": n,
        "verdict": verdict,
        "verdict_reason": reason,
        "take_rate": {
            "rate": round(take_rate, 4), "takes": take_count,
            "first_showings": n,
            "wilson_95": [round(max(0.0, centre - spread), 4),
                          round(min(1.0, centre + spread), 4)],
        },
        "consistency": {
            "pairs": int(len(pair_frame)),
            "take_skip_kappa": None if kappa is None else round(kappa, 4),
            "raw_agreement": (None if pair_frame.empty else round(float(
                (pair_frame["first_action"] == pair_frame["second_action"]).mean()), 4)),
            "both_taken_pairs": int(len(both_taken)),
            "direction_agreement": (None if direction_agreement is None
                                    else round(direction_agreement, 4)),
            "recall_caveat": (
                "Repeats are the same decision on a differently framed chart, "
                "so recall inflates this. Read it as an upper bound."),
        },
        "pace": {
            "median_seconds_per_skip": (None if not np.isfinite(skip_seconds)
                                        else round(skip_seconds, 1)),
            "median_seconds_per_take": (None if not np.isfinite(take_seconds)
                                        else round(take_seconds, 1)),
            "total_minutes": (None if seconds.dropna().empty
                              else round(float(seconds.sum()) / 60.0, 1)),
        },
        "geometry_violations": violations,
        "stage_2_sizing": sizing,
        "sizing_assumption": {
            "sigma_r": ASSUMED_SIGMA_R,
            "note": ("Per-trade dispersion is assumed, not measured -- Stage 0 "
                     "reads no outcome. Every hour in the sizing table moves "
                     "with the square of this number."),
        },
    }
