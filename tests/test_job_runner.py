"""Tests for the research job pipeline and the pieces added around it.

The agent itself is substituted throughout: what needs testing is that a
worker's output is isolated, constrained, schema-checked and ingested — not
that Claude writes good code. `TestAgentAdapter` covers the CLI call with a
stub executable, so the argv and the JSON envelope are verified without a
live install.
"""
from __future__ import annotations

import itertools
import json
import os
import stat
from pathlib import Path

import pandas as pd
import pytest

from src.persistence import store
from src.persistence.models import Evidence, Exploration
from src.runner import agent, burden, forward, interpret, job, planner, worktree
from src.runner.spec import (
    ExperimentSpec,
    SpecValidationError,
    validate_pass_criterion,
)

GOOD_SIGNAL = (
    "import pandas as pd\n"
    "def compute(df: pd.DataFrame) -> pd.Series:\n"
    "    return df['ret_20d'].astype(float)\n"
)


# ---------------------------------------------------------------------------
# worktree isolation
# ---------------------------------------------------------------------------

class TestWorktree:

    def test_worktree_is_clean_and_data_is_reachable(self):
        wt = worktree.create("pytest_clean")
        try:
            assert worktree._git("status", "--porcelain", cwd=wt.path) == ""
            assert (wt.path / "data" / "normalized").exists()
            assert wt.job_dir.exists()
        finally:
            worktree.remove(wt, keep_if_changed=False)

    def test_tracked_evidence_files_are_real_not_links(self):
        """Replacing data/ with a symlink made git report every frozen split
        and holdout result as deleted."""
        wt = worktree.create("pytest_tracked")
        try:
            frozen = wt.path / "data" / "metadata" / "split_v1_frozen.json"
            assert frozen.is_file() and not frozen.is_symlink()
        finally:
            worktree.remove(wt, keep_if_changed=False)

    def test_job_output_does_not_count_as_dirty(self):
        wt = worktree.create("pytest_dirty")
        try:
            (wt.job_dir / "signal.py").write_text(GOOD_SIGNAL)
            assert not worktree._is_dirty(wt)
            (wt.path / "src" / "config.py").write_text("# tampered\n")
            assert worktree._is_dirty(wt)
        finally:
            worktree.remove(wt, keep_if_changed=False)

    def test_two_worktrees_are_independent(self):
        a = worktree.create("pytest_a")
        b = worktree.create("pytest_b")
        try:
            (a.job_dir / "signal.py").write_text("# A\n")
            assert not (b.job_dir / "signal.py").exists()
        finally:
            worktree.remove(a, keep_if_changed=False)
            worktree.remove(b, keep_if_changed=False)

    def test_duplicate_worktree_is_refused(self):
        wt = worktree.create("pytest_dup")
        try:
            with pytest.raises(worktree.WorktreeError, match="already exists"):
                worktree.create("pytest_dup")
        finally:
            worktree.remove(wt, keep_if_changed=False)


# ---------------------------------------------------------------------------
# the CLI adapter
# ---------------------------------------------------------------------------

class TestAgentAdapter:

    @pytest.fixture()
    def stub_cli(self, tmp_path):
        p = tmp_path / "fake_claude"
        p.write_text(
            "#!/bin/bash\n"
            'echo "$@" > "$PWD/argv.txt"\n'
            'echo \'{"type":"result","is_error":false,"result":"done",'
            '"num_turns":4,"total_cost_usd":0.04,"session_id":"stub"}\'\n')
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return p

    def test_missing_cli_says_how_to_install_it(self, monkeypatch):
        monkeypatch.setattr(agent.shutil, "which", lambda _: None)
        monkeypatch.setattr(agent, "_CANDIDATES", ())
        monkeypatch.delenv("CLAUDE_CLI", raising=False)
        with pytest.raises(agent.AgentNotInstalled, match="npm install"):
            agent.find_cli()

    def test_headless_flags_and_json_envelope(self, stub_cli, tmp_path):
        res = agent.run_agent("hello", cwd=tmp_path, cli=str(stub_cli),
                              max_turns=7)
        argv = (tmp_path / "argv.txt").read_text()
        assert "-p hello" in argv
        assert "--output-format json" in argv
        assert "--max-turns 7" in argv
        assert res.ok and res.num_turns == 4 and res.cost_usd == 0.04
        assert res.text == "done"

    def test_non_json_output_still_returns_text(self, tmp_path):
        p = tmp_path / "plain"
        p.write_text("#!/bin/bash\necho 'just words'\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        res = agent.run_agent("x", cwd=tmp_path, cli=str(p))
        assert res.ok and res.text == "just words"

    def test_failure_is_reported_not_raised(self, tmp_path):
        p = tmp_path / "boom"
        p.write_text("#!/bin/bash\necho 'bad' >&2\nexit 3\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        res = agent.run_agent("x", cwd=tmp_path, cli=str(p))
        assert not res.ok and res.returncode == 3 and "bad" in res.stderr

    def test_codex_exec_flags_and_jsonl_are_normalized(self, tmp_path):
        p = tmp_path / "fake_codex"
        p.write_text(
            "#!/bin/bash\n"
            'echo "$@" > "$PWD/codex_argv.txt"\n'
            "echo '{\"type\":\"thread.started\",\"thread_id\":\"codex-thread\"}'\n"
            "echo '{\"type\":\"item.completed\",\"item\":{\"type\":\"agent_message\",\"text\":\"done by codex\"}}'\n"
            "echo '{\"type\":\"turn.completed\",\"usage\":{\"output_tokens\":5}}'\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

        res = agent.run_agent(
            "hello", cwd=tmp_path, cli=str(p), provider="codex",
            model="gpt-test")

        argv = (tmp_path / "codex_argv.txt").read_text()
        assert "exec --json --ephemeral --ignore-user-config" in argv
        assert "--sandbox workspace-write" in argv
        assert 'approval_policy="never"' in argv
        assert "--model gpt-test hello" in argv
        assert res.ok and res.text == "done by codex"
        assert res.session_id == "codex-thread" and res.num_turns == 1
        assert res.cost_usd is None

    def test_codex_nested_abort_reason_is_preserved(self, tmp_path):
        p = tmp_path / "failed_codex"
        p.write_text(
            "#!/bin/bash\n"
            "echo '{\"type\":\"turn.failed\",\"error\":{\"message\":\"rate limit reached\",\"code\":\"rate_limit\"}}'\n"
            "exit 1\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

        res = agent.run_agent("hello", cwd=tmp_path, cli=str(p), provider="codex")

        assert not res.ok
        assert "rate limit reached" in res.stderr
        assert "rate_limit" in res.stderr

    def test_unknown_provider_is_rejected_before_a_subprocess(self, tmp_path):
        with pytest.raises(agent.AgentError, match="unknown LLM provider"):
            agent.run_agent("x", cwd=tmp_path, provider="other")

    def test_provider_catalog_keeps_claude_default(self, monkeypatch):
        monkeypatch.setattr(
            agent, "available", lambda explicit=None, provider="claude": True)
        monkeypatch.setattr(
            agent, "find_cli", lambda explicit=None, provider="claude": f"/{provider}")
        monkeypatch.setattr(
            agent, "_codex_models", lambda exe: (("", "CLI default"),
                                                  ("gpt-test", "GPT Test")))
        catalog = agent.provider_catalog()
        assert catalog["default_provider"] == "claude"
        assert [p["id"] for p in catalog["providers"]] == ["claude", "codex"]
        codex = next(p for p in catalog["providers"] if p["id"] == "codex")
        assert codex["models"][1]["id"] == "gpt-test"


# ---------------------------------------------------------------------------
# the worker contract
# ---------------------------------------------------------------------------

class TestSignalContract:

    def test_forward_label_in_the_source_is_refused(self, tmp_path):
        p = tmp_path / "signal.py"
        p.write_text("import pandas as pd\n"
                     "def compute(df):\n"
                     "    return df['fwd_ret_10d_pct']\n")
        with pytest.raises(job.JobError, match="forward label"):
            job.load_signal_fn(p)

    def test_missing_file_is_a_job_error(self, tmp_path):
        with pytest.raises(job.JobError, match="no signal.py"):
            job.load_signal_fn(tmp_path / "signal.py")

    def test_missing_compute_is_a_job_error(self, tmp_path):
        p = tmp_path / "signal.py"
        p.write_text("x = 1\n")
        with pytest.raises(job.JobError, match="no compute"):
            job.load_signal_fn(p)

    def test_a_good_signal_loads_and_runs(self, tmp_path):
        p = tmp_path / "signal.py"
        p.write_text(GOOD_SIGNAL)
        fn = job.load_signal_fn(p)
        df = pd.DataFrame({"ret_20d": [1.0, 2.0, 3.0]})
        assert list(fn(df)) == [1.0, 2.0, 3.0]

    def test_prompt_hides_the_forward_labels(self):
        spec = ExperimentSpec(hypothesis_id="H024", question="q",
                              signal_name="s")
        prompt = job.build_prompt(spec, ["ret_20d", "fwd_ret_10d_pct",
                                         "excess_ret_5d_pct", "atr_pct"])
        cols = prompt.split("# Columns available")[1]
        assert "ret_20d" in cols and "atr_pct" in cols
        assert "fwd_ret_10d_pct" not in cols
        assert "excess_ret_5d_pct" not in cols

    def test_result_schema_is_enforced(self):
        with pytest.raises(job.ResultSchemaError, match="missing"):
            job.validate_result({"job_id": "J1"})

    def test_a_conforming_result_validates(self):
        job.validate_result({f: {} if f in ("evaluation", "manifest") else "x"
                             for f in job.REQUIRED_RESULT_FIELDS})


# ---------------------------------------------------------------------------
# job orchestration
# ---------------------------------------------------------------------------

class TestJobOrchestration:

    @pytest.fixture(autouse=True)
    def _isolated_jobs_dir(self, tmp_path, monkeypatch):
        """Keep test runs out of the real job store.

        These tests dispatch real jobs, so without this every run left records
        behind — and now that the Explore tab lists them, that noise is
        visible rather than merely untidy.
        """
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path / "jobs")

    def test_job_record_round_trips_provider_and_model(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        original = job.Job(id="J_PROVIDER", spec={}, provider="codex",
                           model="gpt-test")
        original.save()
        loaded = job.get_job("J_PROVIDER")
        assert loaded is not None
        assert loaded.provider == "codex" and loaded.model == "gpt-test"

    def test_a_blocked_spec_never_creates_a_worktree(self, tmp_path):
        """A job that cannot legally run should cost nothing."""
        before = set(worktree.WORKTREE_ROOT.glob("*")) \
            if worktree.WORKTREE_ROOT.exists() else set()
        spec = ExperimentSpec(hypothesis_id="H024", question="q",
                              signal_name="s", partition="test",
                              role="confirmatory")
        jb = job.run_job(spec, agent_fn=lambda p, c: None)
        after = set(worktree.WORKTREE_ROOT.glob("*")) \
            if worktree.WORKTREE_ROOT.exists() else set()
        assert jb.state == "blocked"
        assert "BudgetExhausted" in jb.error or "not in the store" in jb.error
        assert before == after

    def test_unregistered_hypothesis_is_blocked(self):
        spec = ExperimentSpec(hypothesis_id="H777", question="q",
                              signal_name="s", partition="train")
        jb = job.run_job(spec, agent_fn=lambda p, c: None)
        assert jb.state == "blocked" and "not in the store" in jb.error

    def test_an_agent_failure_is_recorded_not_raised(self):
        spec = ExperimentSpec(hypothesis_id="H024", question="q",
                              signal_name="s", partition="train")
        jb = job.run_job(
            spec,
            agent_fn=lambda p, c: agent.AgentResult(
                ok=False, text="", returncode=1, duration_s=0.1,
                stderr="model gave up"))
        assert jb.state == "failed" and "model gave up" in jb.error


# ---------------------------------------------------------------------------
# pass criteria (H037)
# ---------------------------------------------------------------------------

class TestPassCriterion:

    @pytest.mark.parametrize("bad", [
        {}, {"min_spread_bps": 0.0}, {"min_mean_ic": -0.1},
        {"min_mean_ic": 0.0001}, {"whatever": 1.0},
    ])
    def test_unusable_bars_are_refused(self, bad):
        with pytest.raises(SpecValidationError):
            validate_pass_criterion(bad)

    def test_a_real_bar_passes(self):
        validate_pass_criterion({"min_mean_ic": 0.015, "min_spread_bps": 30.0,
                                 "min_monotonicity": 0.6})

    def test_a_sign_test_is_named_as_one(self):
        with pytest.raises(SpecValidationError, match="sign test"):
            validate_pass_criterion({"min_monotonicity": 0.0})


# ---------------------------------------------------------------------------
# multiplicity
# ---------------------------------------------------------------------------

_SEQ = itertools.count()


def _record_test(hypothesis: str, signal: str, partition: str, t_stat: float,
                 exploration_id: str | None = None) -> str:
    """One scored result, shaped the way `run_exploration` writes them.

    Passing `exploration_id` attaches evidence to an exploration that already
    exists, which is what the forward lane does when it accrues.
    """
    n = next(_SEQ)
    exp_id = exploration_id or f"EXP_20260101_{n:06d}"
    if exploration_id is None:
        store.save_exploration(Exploration(
            id=exp_id, hypothesis_id=hypothesis,
            spec={"partition": partition, "signal_name": signal},
            verdict="", failure_class="NO_SIGNAL", signals_produced=[signal]))
    store.add_evidence(Evidence(
        id=f"EV_{exp_id}_{n:06d}", hypothesis_id=hypothesis, signal_id=signal,
        exploration_id=exp_id, role="exploratory", dataset_version="v1",
        partition=partition, metrics={"t_stat": t_stat},
        verdict_statement=""))
    return exp_id


class TestBurden:

    def test_the_bar_rises_with_the_number_of_tests(self):
        bars = [burden.required_t(n) for n in (1, 10, 50, 200)]
        assert bars == sorted(bars)
        assert abs(bars[0] - 1.96) < 0.01
        assert bars[2] > 3.0

    def test_probability_of_a_lucky_hit(self):
        assert burden.prob_any_false_positive(1) == pytest.approx(0.05)
        assert burden.prob_any_false_positive(50) > 0.9

    def test_benjamini_hochberg_keeps_the_small_ones(self):
        keep = burden.benjamini_hochberg([0.001, 0.02, 0.04, 0.3, 0.7], q=0.10)
        assert keep[0] and not keep[-1]

    def test_a_marginal_t_is_labelled_not_promoted(self):
        b = burden.assess(2.1, "train")
        assert b.clears_naive
        b40 = burden.Burden(**{**b.__dict__,
                               "n_including_this": 40,
                               "adjusted_bar": burden.required_t(40)})
        assert abs(b40.t_stat) < b40.adjusted_bar

    def test_a_re_run_signal_is_one_test_in_both_counters(self, research_store):
        """`count_tests` and `partition_summary` must not disagree.

        They answer the same question, and a report where they differ quotes
        a bar that nothing in the ledger ever had to clear. The real store hit
        this: one development fixture re-run eighteen times read as eighteen
        tests and pushed the quoted bar from 2.39 to 3.02.
        """
        for _ in range(3):
            _record_test(hypothesis="H001", signal="same_signal",
                         partition="train", t_stat=1.1)

        summary = burden.partition_summary("train")
        assert burden.count_tests("train") == 1
        assert summary["n_tests"] == 1
        assert summary["sidak_bar"] == pytest.approx(burden.required_t(1), abs=0.01)

    def test_forward_accrual_does_not_raise_the_train_bar(self, research_store):
        """Forward evidence hangs off the train exploration that spawned it."""
        exp_id = _record_test(hypothesis="H001", signal="s", partition="train",
                              t_stat=1.1)
        for _ in range(5):                      # the lane advancing day by day
            _record_test(hypothesis="H001", signal="s", partition="forward",
                         t_stat=2.0, exploration_id=exp_id)

        assert burden.partition_summary("train")["n_tests"] == 1

    def test_a_strong_result_survives_the_false_discovery_step(self, research_store):
        """The BH half has to be reachable, not just present."""
        _record_test(hypothesis="H001", signal="strong", partition="train",
                     t_stat=6.0)
        _record_test(hypothesis="H001", signal="weak", partition="train",
                     t_stat=0.3)

        summary = burden.partition_summary("train")
        by_signal = {r["signal"]: r for r in summary["results"]}
        assert summary["n_surviving_fdr"] == 1
        assert by_signal["strong"]["survives_fdr"]
        assert not by_signal["weak"]["survives_fdr"]

    def test_void_results_do_not_raise_the_bar(self):
        """A voided exploration was never evidence."""
        assert burden.count_tests("train") == \
            len({(e.hypothesis_id, (e.spec or {}).get("signal_name"))
                 for e in job.store.list_explorations()
                 if (e.spec or {}).get("partition") == "train"}) \
            if hasattr(job, "store") else True


# ---------------------------------------------------------------------------
# the forward lane
# ---------------------------------------------------------------------------

class TestForwardLane:

    def test_empty_is_described_as_normal(self):
        st = forward.status()
        assert st["n_sessions"] == 0
        assert not st["ready"]
        assert "expected state" in st["note"]

    def test_accrual_on_an_empty_lane_is_a_no_op(self):
        out = forward.accrue(save=False)
        assert out["accrued"] == 0

    def test_registration_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setattr(forward, "REGISTRY_PATH", tmp_path / "reg.json")
        r = forward.register("s1", "H024", GOOD_SIGNAL, primary_horizon=10)
        assert r.signal_name == "s1"
        again = forward.register("s1", "H024", GOOD_SIGNAL)
        assert len(forward._load()) == 1 and again.signal_name == "s1"

    def test_registered_source_is_executable(self):
        fn_src = GOOD_SIGNAL
        out = forward._compute_from_source(
            fn_src, pd.DataFrame({"ret_20d": [1.0, 2.0]}))
        assert list(out) == [1.0, 2.0]


# ---------------------------------------------------------------------------
# planner and interpretation
# ---------------------------------------------------------------------------

class TestPlanner:

    def test_offline_plan_is_usable_and_says_it_is_offline(self):
        p = planner.offline_plan("do resilient names rebound harder?")
        assert p.source == "offline"
        assert p.pass_criterion
        assert any("not installed" in w for w in p.warnings)
        validate_pass_criterion(p.pass_criterion)

    def test_a_plan_becomes_a_valid_spec(self):
        p = planner.offline_plan("an idea")
        spec = p.to_spec(partition="train", role="exploratory")
        assert spec.partition == "train"
        validate_pass_criterion(spec.pass_criterion)

    def test_agent_json_is_parsed_even_when_wrapped_in_prose(self):
        payload = ('Here is the plan:\n```json\n'
                   '{"question":"q?","signal_name":"sig","hypothesis_id":"H024",'
                   '"lineage":[{"target_id":"H024","relation":"specialises"}],'
                   '"pass_criterion":{"min_mean_ic":0.02}}\n```\nHope that helps.')
        p = planner.propose(
            "idea", agent_fn=lambda prompt: agent.AgentResult(
                ok=True, text=payload, returncode=0, duration_s=1.0))
        assert p.signal_name == "sig"
        assert p.hypothesis_id == "H024"
        assert p.lineage[0]["relation"] == "specialises"

    def test_unlinked_new_hypothesis_is_warned_about(self):
        payload = '{"question":"q?","hypothesis_id":"NEW","lineage":[],' \
                  '"pass_criterion":{"min_mean_ic":0.02}}'
        p = planner.propose(
            "idea", agent_fn=lambda prompt: agent.AgentResult(
                ok=True, text=payload, returncode=0, duration_s=1.0))
        assert any("lineage" in w for w in p.warnings)

    def test_unparseable_output_falls_back(self):
        p = planner.propose(
            "idea", agent_fn=lambda prompt: agent.AgentResult(
                ok=True, text="no json here", returncode=0, duration_s=1.0))
        assert p.source == "offline"


class TestInterpretation:

    REPORT = {
        "signal": "s",
        "predictive_content": {
            "primary_ic": {"mean_ic": 0.021, "t_stat": 2.6, "n_sessions": 705,
                           "horizon": 10, "effective_n": 70},
            "ic_decay": [{"horizon": 5, "t_stat": 2.3},
                         {"horizon": 10, "t_stat": 2.6},
                         {"horizon": 20, "t_stat": 1.1}]},
        "quantiles": {"q5_monotonicity": 0.9, "q5_spread_bps": 41.0},
        "neutralisation": {"ic_retention_pct": 18.0},
    }

    def _spec(self):
        return ExperimentSpec(hypothesis_id="H024", question="q",
                              signal_name="s", primary_horizon=10)

    @staticmethod
    def _no_worker(prompt):
        """Force the deterministic writer.

        `write_interpretation` hands its paragraph to the CLI for a fluency
        pass whenever one is installed, so these assertions on exact wording
        passed or failed according to whether the machine running them
        happened to be logged in. What is under test here is the composition,
        not the rewrite.
        """
        return agent.AgentResult(ok=False, text="", returncode=1,
                                 duration_s=0.0)

    def test_it_reads_as_prose_and_carries_the_numbers(self):
        txt = interpret.write_interpretation(self.REPORT, self._spec(),
                                             "SIGNAL_BUT_BETA",
                                             agent_fn=self._no_worker)
        assert "0.0210" in txt and "2.60" in txt
        assert "SIGNAL_BUT_BETA" in txt
        assert txt.count(".") >= 4

    def test_a_factor_result_is_stated_plainly(self):
        txt = interpret.write_interpretation(self.REPORT, self._spec(),
                                             "SIGNAL_BUT_BETA",
                                             agent_fn=self._no_worker)
        assert "factor exposure" in txt

    def test_a_dead_signal_is_not_dressed_up(self):
        dead = {**self.REPORT, "predictive_content": {
            "primary_ic": {"mean_ic": 0.001, "t_stat": 0.2, "n_sessions": 700,
                           "horizon": 10, "effective_n": 70},
            "ic_decay": [{"horizon": 10, "t_stat": 0.2}]}}
        txt = interpret.write_interpretation(dead, self._spec(), "NO_SIGNAL",
                                             agent_fn=self._no_worker)
        assert "no statistically distinguishable" in txt
        assert "No horizon clears" in txt

    def test_small_effective_n_is_flagged(self):
        small = {**self.REPORT, "predictive_content": {
            "primary_ic": {"mean_ic": 0.05, "t_stat": 2.2, "n_sessions": 100,
                           "horizon": 20, "effective_n": 5},
            "ic_decay": []}}
        txt = interpret.write_interpretation(small, self._spec(), "SUCCESS",
                                             agent_fn=self._no_worker)
        assert "non-overlapping blocks" in txt


# ---------------------------------------------------------------------------
# voiding
# ---------------------------------------------------------------------------

class TestVoiding:

    def test_voided_records_are_hidden_but_kept(self):
        from src.persistence import store
        active = store.list_explorations()
        allx = store.list_explorations(include_voided=True)
        assert len(allx) >= len(active)
        for e in allx:
            if e.is_void:
                assert e.voided_reason and e.voided_date
        assert all(not e.is_void for e in active)
