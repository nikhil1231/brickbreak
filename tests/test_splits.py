"""Tests for the dataset splits.

The split is the irreversible part of the refactor: every result the lab ever
produces is denominated in it, and a partition that leaks is a partition that
manufactures results nobody can retract. So the invariants are tested on
synthetic calendars, where the answer is known by construction, and then
verified on the real panel.

The one that matters most is `test_no_label_crosses_into_a_higher_priority_set`.
Everything else in this file is bookkeeping by comparison.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research_data import splits as S


# ---------------------------------------------------------------------------
# synthetic fixtures — no real data, so the expected answer is arithmetic
# ---------------------------------------------------------------------------

def _synthetic_sessions(years: int = 6, per_quarter: int = 60
                        ) -> pd.DatetimeIndex:
    """A fake calendar with an exact, known number of sessions per quarter.

    Stops before `SplitConfig.forward_start` so the forward lane is empty,
    which is the state a freshly created dataset version is actually in.
    """
    out = []
    for y in range(2020, 2020 + years):
        for q, month in enumerate((1, 4, 7, 10)):
            start = pd.Timestamp(year=y, month=month, day=1)
            out.extend(pd.date_range(start, periods=per_quarter, freq="D"))
    return pd.DatetimeIndex(sorted(out))


def _synthetic_market(sess: pd.DatetimeIndex) -> pd.DataFrame:
    """A market series with enough spread that the terciles are not degenerate."""
    rng = np.random.default_rng(7)
    q = pd.PeriodIndex(sess, freq="Q")
    codes = pd.factorize(q)[0]
    return pd.DataFrame({
        "date": sess,
        "mkt_vol_20d": 10 + 20 * rng.random(len(q))[codes % len(q)] + codes % 5,
        "mkt_trend_eff": 0.1 + 0.5 * ((codes * 7) % 11) / 11,
        "mkt_ret_20d": rng.normal(0, 2, len(sess)),
    })


@pytest.fixture(scope="module")
def synth():
    sess = _synthetic_sessions()
    cfg = S.SplitConfig(version="synthetic")
    m = S.build(cfg, sess=sess, market=_synthetic_market(sess))
    return sess, cfg, m


@pytest.fixture(scope="module")
def real():
    """The actual frozen-shape split over the real panel. Read-only."""
    sess = S.sessions()
    m = S.build(S.SplitConfig(), sess=sess)
    return sess, m


# ---------------------------------------------------------------------------
# the leakage invariants
# ---------------------------------------------------------------------------

def _label_crossings(sess, part, horizon):
    """Kept sessions whose label window reaches a kept higher-priority set."""
    kept = part[part != ""]
    pos = {d: i for i, d in enumerate(sess)}
    bad = []
    for d, s in kept.items():
        i = pos[d]
        for nxt in sess[i + 1: i + 1 + horizon]:
            o = part.get(nxt, "")
            if o and o != s and S.PRIORITY[o] > S.PRIORITY[s]:
                bad.append((d, s, nxt, o))
                break
    return bad


def test_no_label_crosses_into_a_higher_priority_set(synth):
    """No kept row's forward window can reach a set that outranks it.

    This is what the purge exists for. A train row whose +20d label is
    determined by price action inside a test quarter has, in effect, been
    trained on the test set.
    """
    sess, cfg, m = synth
    part = S.session_partitions(m, sess=sess)
    assert _label_crossings(sess, part, cfg.max_horizon) == []


def test_no_label_crossing_on_the_real_panel(real):
    sess, m = real
    part = S.session_partitions(m, sess=sess)
    cfg = S.SplitConfig(**m["config"])
    assert _label_crossings(sess, part, cfg.max_horizon) == []


def test_a_shorter_purge_would_have_leaked(synth):
    """The purge is load-bearing, not decorative.

    Rebuilding the same assignment with the purge disabled must reintroduce
    crossings. If it does not, the test above proves nothing.
    """
    sess, cfg, m = synth
    meta = pd.DataFrame(m["quarters"])
    meta["start"] = pd.to_datetime(meta["start"])
    meta["end"] = pd.to_datetime(meta["end"])
    raw, _, _ = S.purge(sess, meta, S.SplitConfig(max_horizon=0, embargo=0))
    assert _label_crossings(sess, raw, cfg.max_horizon)


def test_every_session_has_exactly_one_partition(real):
    sess, m = real
    part = S.session_partitions(m, sess=sess)
    assert len(part) == len(sess)
    assert part.index.is_unique
    assert set(part.unique()) <= set(S.SETS) | {"", "forward"}


def test_purge_never_takes_from_test(real):
    """Evaluation sample is the scarce resource; training rows are not."""
    _, m = real
    assert m["purge"]["dropped_by_set"]["test"] == 0
    assert m["purge"]["dropped_by_set"]["train"] > 0


def test_purge_cost_is_reported(real):
    _, m = real
    pu = m["purge"]
    assert pu["sessions_dropped"] > 0
    assert 0 < pu["dropped_pct_of_panel"] < 30
    assert len(pu["boundaries"]) == pu["n_boundaries"]


# ---------------------------------------------------------------------------
# the draw
# ---------------------------------------------------------------------------

def test_draw_is_deterministic(synth):
    sess, cfg, m = synth
    again = S.build(cfg, sess=sess, market=_synthetic_market(sess))
    assert again["hash"] == m["hash"]
    assert [q["set"] for q in again["quarters"]] == [q["set"] for q in m["quarters"]]


def test_a_different_seed_gives_a_different_split(synth):
    sess, cfg, m = synth
    other = S.build(S.SplitConfig(version="synthetic", seed=cfg.seed + 500),
                    sess=sess, market=_synthetic_market(sess))
    assert other["hash"] != m["hash"]


def test_constraints_hold(real):
    _, m = real
    cfg = S.SplitConfig(**m["config"])
    meta = pd.DataFrame(m["quarters"])
    meta["year"] = pd.to_datetime(meta["start"]).dt.year
    for s in S.SETS:
        sub = meta[meta["set"] == s]
        assert sub["year"].nunique() >= cfg.min_years_per_set
        assert sub["high_vol"].any()
        assert sub["trending"].any()
    runs, prev = [], None
    for s in meta["set"]:
        runs.append(runs[-1] + 1 if s == prev else 1)
        prev = s
    assert max(runs) <= cfg.max_consecutive


def test_every_quarter_is_assigned_exactly_once(real):
    sess, m = real
    qs = [q["quarter"] for q in m["quarters"]]
    assert len(qs) == len(set(qs)) == m["panel"]["n_quarters"]
    assert sum(m["quarter_counts"].values()) == len(qs)


def test_impossible_constraints_raise_rather_than_relax(synth):
    """A constraint that cannot be met is an error, not a silent loosening."""
    sess, _, _ = synth
    with pytest.raises(S.SplitError, match="no assignment satisfied"):
        S.build(S.SplitConfig(version="x", max_consecutive=0,
                              max_seed_attempts=50),
                sess=sess, market=_synthetic_market(sess))


def test_ratios_must_sum_to_one(synth):
    sess, _, _ = synth
    with pytest.raises(S.SplitError, match="ratios must sum"):
        S.build(S.SplitConfig(version="x", ratios=(0.5, 0.2, 0.2)),
                sess=sess, market=_synthetic_market(sess))


def test_target_counts_allocate_every_quarter():
    for n in range(6, 60):
        c = S._target_counts(n, (0.6, 0.2, 0.2))
        assert sum(c.values()) == n
        assert min(c.values()) >= 1


# ---------------------------------------------------------------------------
# the manifest as evidence
# ---------------------------------------------------------------------------

def test_manifest_hash_detects_editing(tmp_path, synth, monkeypatch):
    _, _, m = synth
    monkeypatch.setattr(S, "SPLIT_DIR", tmp_path)
    S.save(m)
    loaded = S.load(m["version"])
    assert loaded["hash"] == m["hash"]

    p = S.path_for(m["version"])
    edited = json.loads(p.read_text())
    edited["quarters"][0]["set"] = "train" if \
        edited["quarters"][0]["set"] != "train" else "test"
    p.write_text(json.dumps(edited))
    with pytest.raises(S.SplitError, match="edited since it was frozen"):
        S.load(m["version"])


def test_save_refuses_to_overwrite(tmp_path, synth, monkeypatch):
    """Redrawing in place is how a holdout gets spent."""
    _, _, m = synth
    monkeypatch.setattr(S, "SPLIT_DIR", tmp_path)
    S.save(m)
    with pytest.raises(S.SplitError, match="frozen once"):
        S.save(m)
    S.save(m, overwrite=True)


def test_build_writes_nothing(tmp_path, synth, monkeypatch):
    sess, cfg, _ = synth
    monkeypatch.setattr(S, "SPLIT_DIR", tmp_path)
    S.build(cfg, sess=sess, market=_synthetic_market(sess))
    assert list(tmp_path.iterdir()) == []


def test_calendar_hash_changes_with_a_missing_session(real):
    sess, _ = real
    assert S.calendar_hash(sess) != S.calendar_hash(sess.delete(100))


# ---------------------------------------------------------------------------
# using a split
# ---------------------------------------------------------------------------

def test_assign_labels_rows_and_drops_purged(real):
    sess, m = real
    part = S.session_partitions(m, sess=sess)
    df = pd.DataFrame({"date": np.repeat(sess, 2), "symbol": "AAA"})
    out = S.assign(df, manifest=m)
    assert "partition" not in df.columns          # does not mutate its input
    assert (out["partition"] != "").all()
    assert len(out) == 2 * int((part != "").sum())


def test_assign_can_keep_purged_rows_when_asked(real):
    sess, m = real
    df = pd.DataFrame({"date": sess})
    out = S.assign(df, manifest=m, drop_purged=False)
    assert len(out) == len(sess)
    assert (out["partition"] == "").any()


def test_partition_returns_only_its_own_sessions(real):
    _, m = real
    seen = []
    for name in S.SETS:
        idx = S.partition(name, manifest=m)
        assert len(idx) == m["session_counts"][name]
        seen.append(set(idx))
    assert not seen[0] & seen[1] and not seen[1] & seen[2] and not seen[0] & seen[2]


def test_unknown_partition_raises(real):
    _, m = real
    with pytest.raises(S.SplitError, match="unknown partition"):
        S.partition("holdout", manifest=m)


def test_horizon_beyond_the_purge_is_an_error(real):
    _, m = real
    S.check_horizon(m["purge"]["max_horizon"], m)
    with pytest.raises(S.SplitError, match="exceeds split"):
        S.check_horizon(m["purge"]["max_horizon"] + 1, m)


def test_forward_partition_is_chronological_and_after_the_panel(synth):
    """Forward is empty at version creation and fills in as sessions arrive."""
    sess, cfg, m = synth
    assert m["forward"]["n_sessions"] == 0

    later = sess.append(pd.DatetimeIndex(
        pd.date_range(pd.Timestamp(cfg.forward_start), periods=10, freq="D")))
    part = S.session_partitions(m, sess=later)
    fwd = part[part == "forward"]
    assert len(fwd) == 10
    assert fwd.index.min() >= pd.Timestamp(cfg.forward_start)
    assert part[part.index < pd.Timestamp(cfg.forward_start)].ne("forward").all()


# ---------------------------------------------------------------------------
# the ledger
# ---------------------------------------------------------------------------

def test_spent_families_are_blocked_from_the_quarters_they_read(real):
    """2020-2023 was read twice; its readers may not score there again."""
    _, m = real
    for family in ("opening_window", "resilience"):
        blocked = S.blocked_families(m, family)
        assert blocked, f"{family} should be blocked somewhere in test"
    assert S.blocked_families(m, "a_brand_new_idea") == []


def test_exposure_records_role_not_just_the_fact(real):
    _, m = real
    roles = {e["role"] for q in m["quarters"] for e in q["prior_exposure"]}
    assert roles == {"confirmatory", "exploratory"}


def test_exposure_spans_are_inclusive_at_the_edges():
    assert S.exposure_for(pd.Timestamp("2020-12-29"),
                          pd.Timestamp("2020-12-29"))
    assert not S.exposure_for(pd.Timestamp("2019-01-01"),
                              pd.Timestamp("2019-12-31"))
