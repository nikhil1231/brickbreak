"""Tests for exploration progress: phases, the job listing, and the API.

An exploration spends most of its wall-clock inside one state (`running`) and
one step of it (the worker writing the signal). What makes it watchable is the
`phase`, which is why these tests care that it is written to disk as it moves
rather than only at the end — a phase only the running process knows about is
a progress bar that stops at the first thing that goes wrong.
"""
from __future__ import annotations

import json


from src.runner import agent, job
from src.runner.spec import ExperimentSpec


class TestJobListing:
    def test_result_files_are_not_read_as_job_records(self, tmp_path, monkeypatch):
        """Regression: `*_result.json` shares the directory with job records.

        Globbing both handed an experiment result to `Job.from_dict`, which
        raised TypeError and took the entire listing — and `cli jobs` — down
        with it.
        """
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        job.Job(id="JOB_1", spec={"signal_name": "s"}).save()
        (tmp_path / "JOB_1_result.json").write_text(
            json.dumps({"job_id": "JOB_1", "failure_class": "NO_SIGNAL"}))

        jobs = job.list_jobs()
        assert [j.id for j in jobs] == ["JOB_1"]

    def test_newest_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        job.Job(id="JOB_20260101_000000", spec={}).save()
        job.Job(id="JOB_20260102_000000", spec={}).save()
        assert [j.id for j in job.list_jobs()][0] == "JOB_20260102_000000"


class TestPhases:
    def test_a_phase_is_durable_the_moment_it_is_entered(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        jb = job.Job(id="JOB_P", spec={})
        jb.enter("writing the signal")
        assert job.get_job("JOB_P").phase == "writing the signal"

    def test_a_run_reaches_the_worker_phase_before_the_worker_fails(
            self, tmp_path, monkeypatch):
        """The phase names where a failed run got to, not merely that it failed."""
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        seen: list[str] = []
        real_enter = job.Job.enter

        def spy(self, phase):
            seen.append(phase)
            real_enter(self, phase)

        monkeypatch.setattr(job.Job, "enter", spy)

        spec = ExperimentSpec(hypothesis_id="H024", question="q",
                              signal_name="s", partition="train")
        jb = job.run_job(spec, agent_fn=lambda p, c: agent.AgentResult(
            ok=False, text="", returncode=1, duration_s=0.1,
            stderr="model gave up"))

        assert jb.state == "failed"
        assert seen[:4] == ["checking budget", "loading data",
                            "preparing worktree", "writing the signal"]
        assert "evaluating" not in seen
        assert job.get_job(jb.id).phase == "writing the signal"
        assert all(phase in job.PHASES for phase in seen)

    def test_a_blocked_spec_stops_at_the_budget_check(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        spec = ExperimentSpec(hypothesis_id="H777", question="q",
                              signal_name="s", partition="train")
        jb = job.run_job(spec, agent_fn=lambda p, c: None)
        assert jb.state == "blocked"
        assert jb.phase == "checking budget"


class TestHandover:
    def test_an_opened_record_is_continued_rather_than_duplicated(
            self, tmp_path, monkeypatch):
        """One exploration is one job, planning included."""
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        spec = ExperimentSpec(hypothesis_id="H024", question="idea",
                              signal_name="(planning)", partition="train")
        opened = job.open_job(spec, provider="codex", model="gpt-test")
        assert opened.phase == "planning"
        assert opened.state == "running"

        final = ExperimentSpec(hypothesis_id="H024", question="planned q",
                               signal_name="planned_signal", partition="train")
        jb = job.run_job(final, agent_fn=lambda p, c: agent.AgentResult(
            ok=False, text="", returncode=1, duration_s=0.1, stderr="stop"),
            existing=opened)

        assert jb.id == opened.id
        assert len(job.list_jobs()) == 1
        # The record carries the spec it ended up running, not the placeholder
        # it was opened with.
        assert job.get_job(jb.id).spec["signal_name"] == "planned_signal"


class TestOrphans:
    def test_a_job_from_a_dead_process_is_annotated_not_left_running(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        job.Job(id="JOB_ORPHAN", spec={}, state="running",
                phase="writing the signal").save()
        job.Job(id="JOB_DONE", spec={}, state="succeeded", phase="done").save()

        reaped = job.reap_orphans()

        assert [j.id for j in reaped] == ["JOB_ORPHAN"]
        orphan = job.get_job("JOB_ORPHAN")
        assert orphan.state == "interrupted"
        assert "writing the signal" in orphan.error
        assert orphan.finished_at
        # It is annotated, not removed, and nothing finished is touched.
        assert job.get_job("JOB_DONE").state == "succeeded"
        assert len(job.list_jobs()) == 2

    def test_reaping_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        job.Job(id="JOB_ORPHAN", spec={}, state="running", phase="").save()
        job.reap_orphans()
        first = job.get_job("JOB_ORPHAN").error
        assert job.reap_orphans() == []
        assert job.get_job("JOB_ORPHAN").error == first


class TestWorkerProgress:
    """What the long phase reports about itself."""

    def test_nothing_to_report_without_a_worktree(self):
        assert job.worker_progress(job.Job(id="J", spec={}))["signal_written"] is False

    def test_it_sees_the_signal_file_appear(self, tmp_path):
        jb = job.Job(id="J", spec={}, worktree_path=str(tmp_path))
        (tmp_path / "job").mkdir()
        (tmp_path / "job" / "PROMPT.md").write_text("the prompt")

        before = job.worker_progress(jb)
        assert before["signal_written"] is False
        assert before["seconds_since_change"] is not None   # the worktree exists

        (tmp_path / "job" / "signal.py").write_text("def compute(df):\n    return df\n")
        after = job.worker_progress(jb)
        assert after["signal_written"] is True
        assert after["signal_bytes"] > 0

    def test_a_vanished_worktree_is_not_an_error(self, tmp_path):
        jb = job.Job(id="J", spec={}, worktree_path=str(tmp_path / "gone"))
        assert job.worker_progress(jb) == {"signal_written": False,
                                           "signal_bytes": 0,
                                           "seconds_since_change": None}

    def test_entering_a_phase_stamps_when_it_started(self, tmp_path, monkeypatch):
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        jb = job.Job(id="J", spec={})
        assert jb.phase_started_at == ""
        jb.enter("writing the signal")
        assert job.get_job("J").phase_started_at


