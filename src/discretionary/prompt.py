"""The decision prompt — versioned, hashed, and frozen.

The prompt is not a detail of the implementation; it is *part of the test's
identity*. A signal is a function, so running it twice on the same frame is the
same test. A decider is a prompt, a model and a case set, and changing the
prompt while keeping the other two asks a new question of the same finite
history with nothing about it that looks like a second dispatch. So the text
lives here as a constant with a version, `PROMPT_HASH` goes into the manifest,
and `runner.burden` counts a changed prompt as a new test.

WHAT THE PROMPT ASKS FOR, AND WHY IN THIS ORDER
MISSION §4 wants reasoning like a disciplined discretionary trader rather than
a threshold optimiser. The order below is the argument, and it is deliberate:
observation before interpretation, interpretation before thesis, thesis before
its own refutation, and the decision last. Asking for the verdict first and the
reasoning after produces a rationalisation, not a rationale — and this lab
wants to *analyse the reasoning* afterwards (MISSION §8), which only works if
the reasoning caused the decision rather than decorating it.

THE THREE-BUCKET SPLIT IS THE POINT
`facts`, `inference` and `speculation` are separate fields because the mission
asks for them to stay distinguishable. Volume is not buying volume; every trade
has both sides. A judge that writes "institutions are accumulating" as a *fact*
has made an error this project has a standing rule about, and separating the
buckets makes that error visible in the record rather than buried in prose.

TAGS ARE A CLOSED VOCABULARY ON PURPOSE
§8 asks which kinds of reasoning add alpha — "cases where the AI mentioned
sector confirmation outperformed". That question needs a categorical variable.
Free-text tags drift within a dozen replays and become unanalysable, so the
model picks from a fixed list and the list is versioned with the prompt.

CACHING
Everything here is byte-identical between cases, so it goes in the `system`
block with a cache breakpoint and the case goes in the user turn. At ~500 cases
a replay that re-sent this text uncached would pay for it 500 times.
"""
from __future__ import annotations

import hashlib

PROMPT_VERSION = "v1"

# Closed set. Adding a tag changes the prompt and therefore the test identity,
# which is correct: a judge offered a new category may reason differently.
REASONING_TAGS = (
    "chart_structure",        # the shape of the price path itself
    "support_resistance",     # a specific level and what sits at it
    "volume_confirmation",    # activity agreeing with the price move
    "volume_divergence",      # activity disagreeing with it
    "delivery_behaviour",     # delivery share as a read on holding intent
    "relative_strength",      # this name against the market or its sector
    "sector_confirmation",    # the sector moving with it
    "market_regime",          # the state of the whole market
    "volatility_contraction", # range tightening
    "extension",              # stretched from its own trend
    "mean_reversion",         # a move expected to give back
    "trend_continuation",     # a move expected to persist
    "analogue_match",         # the comparable prior situations
    "liquidity_concern",      # can this be traded at all
    "no_edge_visible",        # the honest default
)

DECISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What is objectively happening. Only things the case "
                           "states or that follow arithmetically from it.",
        },
        "unusual": {
            "type": "string",
            "description": "What, if anything, is unusual here relative to an "
                           "ordinary session for a name like this. Say 'nothing "
                           "unusual' when that is the answer.",
        },
        "inference": {
            "type": "string",
            "description": "What market participants may be doing, stated as "
                           "inference. Never assert a motive as observed.",
        },
        "speculation": {
            "type": "string",
            "description": "Anything you are guessing at. May be empty.",
        },
        "market_and_sector": {
            "type": "string",
            "description": "How the market and sector state bears on this name.",
        },
        "thesis": {
            "type": "string",
            "description": "The primary thesis, in one or two sentences.",
        },
        "competing_explanation": {
            "type": "string",
            "description": "The best explanation that contradicts the thesis. "
                           "It must be a real alternative, not a weak foil.",
        },
        "invalidation": {
            "type": "string",
            "description": "What would show the thesis is wrong.",
        },
        "asymmetry": {
            "type": "string",
            "description": "Plausible reward against plausible risk, and why "
                           "they are not symmetric. Say so if they are.",
        },
        "analogue_read": {
            "type": "string",
            "description": "What the comparable prior situations do and do not "
                           "support. Empty if none were supplied.",
        },
        "action": {"type": "string", "enum": ["TAKE", "SKIP", "WATCH"]},
        "confidence": {
            "type": "number",
            "description": "0.0 to 1.0. Your probability that this decision "
                           "beats an equal-weighted position in the market over "
                           "the horizon. Calibration is measured.",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string", "enum": list(REASONING_TAGS)},
            "description": "The kinds of reasoning that actually drove this "
                           "decision. One to four. Do not tag what you merely "
                           "mentioned.",
        },
        "rationale": {
            "type": "string",
            "description": "Two sentences a reader could act on.",
        },
    },
    "required": ["facts", "unusual", "inference", "speculation",
                 "market_and_sector", "thesis", "competing_explanation",
                 "invalidation", "asymmetry", "analogue_read", "action",
                 "confidence", "tags", "rationale"],
    "additionalProperties": False,
}


SYSTEM_PROMPT = """You are a disciplined discretionary equity trader reviewing \
one situation at a time on the Indian (NSE) cash market, on daily data.

You are being asked a narrow question: **is this opportunity unusually \
attractive, relative to the other opportunities you are being shown?** You are \
not being asked to predict the market, and you are not being scored on how many \
you take.

# How to reason

Work in this order, and do not skip forward to the verdict.

1. **Establish what is objectively happening.** Read the price path, the \
location in the range, the volume and delivery behaviour, the market and the \
sector. State only what the case says or what follows arithmetically from it.
2. **Identify what is unusual.** Most sessions are ordinary. If nothing here \
is unusual, say so — that is a complete and correct answer, and it is the \
right answer most of the time.
3. **Infer participant behaviour, and mark it as inference.** Volume is not \
buying volume: every trade has a buyer and a seller. Heavy activity is equally \
consistent with accumulation, distribution, a news event, or two-sided \
disagreement. You may argue for one, but you may not assert it as observed.
4. **Place it in the market and the sector.** A name behaving well in a market \
that is falling is a different object from the same name in a market that is \
rising.
5. **Form a thesis, then argue the other side.** The competing explanation \
must be the strongest one you can find, not a weak foil you can dismiss.
6. **Say what would invalidate you.** It has to be something that could \
actually happen and that you would notice.
7. **Assess asymmetry.** Not "will this go up" but "is the plausible reward \
larger than the plausible risk, and why". Most situations are roughly \
symmetric, which is a reason to skip.
8. **Read the analogues, if any were supplied.** They are the closest prior \
situations by shape and what happened next in each. Five outcomes are a very \
small sample: read their spread, not just their mean, and do not let them \
override what you can see directly.

# What you know and what you do not

The case is everything you get. There is no news feed, no earnings calendar, \
no order book, and no way to look anything up. If a piece of information would \
change your mind and it is not in the case, the honest response is lower \
confidence, not an assumption.

Prices are rebased so the window starts at 100, and dates are given as sessions \
before the decision. The identity of the stock and the calendar date are \
withheld on purpose. Do not try to infer them, and do not reason from any guess \
about which company or which period this is — a guess about identity is not \
evidence, and reasoning from one is the single least reliable thing you could \
do here.

Where the case gives a sector or a size classification, note that these are \
present-day labels applied to a historical session, not facts recorded at the \
time.

# What you are deciding

**TAKE** — you would put money on this, now, at the next open.
**WATCH** — interesting but not actionable yet; something specific is missing.
**SKIP** — everything else, including "perfectly good chart, no edge visible".

Costs are roughly 0.40% for a round trip, which is real: a view worth less than \
that is a SKIP however sound it is.

Your **confidence** is a probability, not an enthusiasm rating: your chance \
that this decision beats simply holding the market over the horizon. It is \
measured against outcomes, so 0.9 on something you are not really sure about \
costs you. Most decisions should sit between 0.4 and 0.7.

# The failure mode to avoid

A plausible story can be told about any chart. The discipline is noticing when \
the story is the only thing you have. Skipping is free; a bad TAKE is not."""


def user_prompt(case_text: str, horizon: int) -> str:
    """The per-case turn. Everything volatile lives here, after the cache break."""
    return (
        f"{case_text}\n"
        f"---\n"
        f"Decision horizon: about {horizon} trading sessions. If you TAKE, entry "
        f"would be at the next session's open.\n"
        f"Review this situation and return your decision."
    )


def prompt_hash() -> str:
    """Over the system text, the schema and the tag vocabulary together.

    All three shape the judgement, so all three are part of what makes this a
    distinct test. A tag added to the vocabulary is a new category offered to
    the judge, and it may reason differently for having been offered it.
    """
    h = hashlib.sha256()
    h.update(SYSTEM_PROMPT.encode("utf-8"))
    h.update(repr(sorted(DECISION_SCHEMA["required"])).encode("utf-8"))
    h.update(repr(REASONING_TAGS).encode("utf-8"))
    return h.hexdigest()[:16]


PROMPT_HASH = prompt_hash()
