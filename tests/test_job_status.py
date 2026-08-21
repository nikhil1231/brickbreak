"""Tests for exploration progress: phases, the job listing, and the API.

An exploration spends most of its wall-clock inside one state (`running`) and
one step of it (the worker writing the signal). What makes it watchable is the
`phase`, which is why these tests care that it is written to disk as it moves
rather than only at the end — a phase only the running process knows about is
a progress bar that stops at the first thing that goes wrong.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from types import SimpleNamespace

import pytest

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


class TestJobsAPI:
    @pytest.fixture
    def server(self, tmp_path, monkeypatch):
        from src.interface import backend
        monkeypatch.setattr(job, "JOBS_DIR", tmp_path)
        srv, _ = backend.serve_backend(port=0, block=False)
        yield srv, backend
        srv.shutdown()

    def _get(self, srv, path):
        with urllib.request.urlopen(
                f"http://127.0.0.1:{srv.server_address[1]}{path}") as res:
            return json.loads(res.read().decode())

    def test_a_running_job_reports_its_phase(self, server, tmp_path):
        srv, _ = server
        jb = job.Job(id="JOB_A", spec={"hypothesis_id": "H024",
                                       "signal_name": "s", "question": "q",
                                       "partition": "train"},
                     state="running", phase="writing the signal")
        jb.save()

        row = self._get(srv, "/api/jobs")["jobs"][0]
        assert row["state"] == "running"
        assert row["phase"] == "writing the signal"
        # A running row carries the evidence that it is not hung.
        assert "worker" in row and row["worker"]["signal_written"] is False
        assert row["phases"] == list(job.PHASES)
        assert row["hypothesis_id"] == "H024"

    def test_a_finished_job_carries_its_verdict(self, server, tmp_path):
        srv, _ = server
        result = tmp_path / "JOB_B_result.json"
        result.write_text(json.dumps({"failure_class": "NO_SIGNAL",
                                      "interpretation": "nothing here"}))
        job.Job(id="JOB_B", spec={"signal_name": "s"}, state="succeeded",
                phase="done", result_path=str(result), runtime_s=12.5).save()

        row = self._get(srv, "/api/jobs")["jobs"][0]
        assert row["failure_class"] == "NO_SIGNAL"
        assert row["interpretation"] == "nothing here"
        assert row["runtime_s"] == 12.5

    def test_a_missing_result_file_does_not_break_the_listing(self, server):
        srv, _ = server
        job.Job(id="JOB_C", spec={}, state="succeeded",
                result_path="/nowhere/gone.json").save()
        row = self._get(srv, "/api/jobs")["jobs"][0]
        assert row["failure_class"] == ""

    def test_an_exploration_in_flight_does_not_block_the_status_poll(self, server,
                                                                    monkeypatch):
        """The whole point of the progress list.

        On the single-threaded server this replaced, a request that held open
        for the length of an exploration held every other request with it, so
        the list could only refresh once there was nothing left to watch.
        """
        srv, backend = server
        monkeypatch.setattr(backend.agent, "available", lambda provider: True)

        def slow_run_job(exp_spec, provider, model, existing=None):
            time.sleep(2.0)
            return SimpleNamespace(state="failed", id="JOB_SLOW", error="done",
                                   provider=provider, model=model,
                                   agent_session="")

        monkeypatch.setattr(backend.job, "run_job", slow_run_job)

        def launch():
            request = urllib.request.Request(
                f"http://127.0.0.1:{srv.server_address[1]}/api/explore",
                data=json.dumps({"hypothesis_id": "H024", "provider": "claude",
                                 "question": "q", "signal_name": "s"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(request)
            except urllib.error.HTTPError:
                pass                      # the fake job fails; that is fine

        thread = threading.Thread(target=launch, daemon=True)
        thread.start()
        time.sleep(0.3)

        t0 = time.time()
        self._get(srv, "/api/jobs")
        assert time.time() - t0 < 1.0, "the status poll waited on the exploration"
        thread.join(timeout=5)
