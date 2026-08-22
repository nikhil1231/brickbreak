"""Reading NSE result filings, and refusing to flatten them carelessly.

The fixture is the shape of a real in-bse-fin filing, including the property
that makes a naive wide-table reduction wrong: two contexts with identical
periods, no dimensions, and different values.
"""
from __future__ import annotations

import pandas as pd

from src.research_data.sources import xbrl

FILING = b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
            xmlns:in-bse-fin="http://www.bseindia.com/xbrl/fin/2019-09-30/in-bse-fin">
  <xbrli:context id="OneD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">HDFCBANK</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="FourD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">HDFCBANK</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="SegD">
    <xbrli:entity><xbrli:identifier scheme="http://www.nseindia.com/NSESymbol">HDFCBANK</xbrli:identifier>
      <xbrli:segment><xbrldi:explicitMember dimension="in-bse-fin:SegmentAxis">in-bse-fin:TreasuryMember</xbrldi:explicitMember></xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-10-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  <in-bse-fin:InterestEarned contextRef="OneD" unitRef="INR" decimals="-5">850401700000</in-bse-fin:InterestEarned>
  <in-bse-fin:InterestEarned contextRef="FourD" unitRef="INR" decimals="-5">2495881300000</in-bse-fin:InterestEarned>
  <in-bse-fin:InterestEarned contextRef="SegD" unitRef="INR" decimals="-5">120000000000</in-bse-fin:InterestEarned>
  <in-bse-fin:DescriptionOfPresentationCurrency contextRef="OneD">INR</in-bse-fin:DescriptionOfPresentationCurrency>
</xbrli:xbrl>
"""


def test_facts_carry_their_context_period_and_unit():
    facts = xbrl.parse_facts(FILING)
    row = facts[facts["context_ref"] == "OneD"].iloc[0]
    assert row["element"] == "InterestEarned"
    assert row["period_start"] == pd.Timestamp("2024-10-01")
    assert row["period_end"] == pd.Timestamp("2024-12-31")
    assert row["unit"] == "INR"
    assert row["value_num"] == 850401700000


def test_dimensions_are_captured_so_segments_can_be_excluded():
    facts = xbrl.parse_facts(FILING)
    seg = facts[facts["context_ref"] == "SegD"].iloc[0]
    assert seg["dimensions"] == "SegmentAxis=TreasuryMember"
    assert facts[facts["context_ref"] == "OneD"]["dimensions"].isna().all()


def test_narrative_facts_survive_as_text_rather_than_becoming_nan_rows():
    facts = xbrl.parse_facts(FILING)
    row = facts[facts["element"] == "DescriptionOfPresentationCurrency"].iloc[0]
    assert row["value_text"] == "INR"
    assert pd.isna(row["value_num"])


def test_the_period_does_not_identify_a_fact():
    """`OneD` and `FourD` share an entity, a period and no dimensions.

    This is the measured behaviour of real filings, not a contrived case: the
    quarter and the year-to-date column carry the same dates, and only the
    context id separates them. 30 such collisions in HDFC Bank's Q3 FY25
    banking filing, 37 in Reliance's. A reduction keyed on
    (element, period) therefore picks one of two very different numbers by
    row order — 850bn or 2,496bn here — in about a third of the line items.
    """
    ambiguous = xbrl.ambiguous_facts(xbrl.parse_facts(FILING))
    row = ambiguous[ambiguous["element"] == "InterestEarned"].iloc[0]
    assert row["n_values"] == 2
    assert row["contexts"] == "FourD|OneD"


def test_facts_for_excludes_segment_contexts_by_default():
    got = xbrl.facts_for(FILING, ["InterestEarned"])
    assert set(got["context_ref"]) == {"OneD", "FourD"}
    assert "SegD" not in set(got["context_ref"])


def test_facts_for_can_ask_for_one_segment():
    got = xbrl.facts_for(FILING, ["InterestEarned"],
                         dimensions="SegmentAxis=TreasuryMember")
    assert got["value_num"].tolist() == [120000000000]


def test_an_unparseable_filing_returns_an_empty_frame_not_an_exception():
    """A truncated download must not take a whole archive walk down."""
    assert xbrl.parse_facts(b"").empty
    assert list(xbrl.parse_facts(b"").columns) == xbrl.FACT_COLUMNS


def test_storage_is_content_addressed(tmp_path, monkeypatch):
    """Two URLs serving identical bytes are one archived object; a rewrite at
    the same URL is a second one, which is how a silent restatement shows up."""
    monkeypatch.setattr(xbrl, "ARCHIVE_DIR", tmp_path)
    sha_a, path_a = xbrl.store(FILING)
    sha_b, path_b = xbrl.store(FILING)
    assert sha_a == sha_b and path_a == path_b
    sha_c, _ = xbrl.store(FILING + b"<!-- revised -->")
    assert sha_c != sha_a
    monkeypatch.setattr(xbrl, "blob_path",
                        lambda s: tmp_path / s[:2] / f"{s}.xml")
    assert xbrl.read(sha_a) == FILING
