"""The small, deliberately hand-picked test universe for this spike."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestSecurity:
    nse_symbol: str
    kind: str      # liquid | less_liquid | inactive
    note: str = ""


# 5 liquid large caps, a couple of thinner names, and securities that are no
# longer traded (merged/delisted) to probe survivorship-bias handling.
TEST_UNIVERSE: list[TestSecurity] = [
    TestSecurity("RELIANCE", "liquid", "largest cap, longest history"),
    TestSecurity("INFY", "liquid", "IT major"),
    TestSecurity("TCS", "liquid", "listed 2004, tests pre-2010 depth"),
    TestSecurity("HDFCBANK", "liquid", "survived a major merger (HDFC Ltd, 2023)"),
    TestSecurity("ICICIBANK", "liquid", "broker's own group"),
    TestSecurity("NELCAST", "less_liquid", "small cap, thin volume"),
    TestSecurity("KAKATCEM", "less_liquid", "small cap cement"),
    # Inactive: all merged/delisted, and all carry Token=0 in the scrip master.
    TestSecurity("ANDHRABANK", "inactive", "merged into Union Bank, Apr 2020"),
    TestSecurity("CENTBOP", "inactive", "Centurion BoP, merged into HDFC Bank 2008"),
    TestSecurity("BHARATFIN", "inactive", "merged into IndusInd Bank, Jul 2019"),
]


def by_kind(kind: str) -> list[TestSecurity]:
    return [s for s in TEST_UNIVERSE if s.kind == kind]
