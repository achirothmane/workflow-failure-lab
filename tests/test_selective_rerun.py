from ci_retry_gate import PROVENANCE_CONFIRMED, PROVENANCE_UNAVAILABLE, assess_job
from selective_rerun import (
    execute_selective_epoch,
    revalidate_selective_job_binding,
    selective_plan,
)


def fake_job(job_id, name="tests", steps=None):
    return {
        "id": job_id,
        "name": name,
        "started_at": "2026-09-17T01:00:00Z",
        "completed_at": "2026-09-17T01:02:00Z",
        "steps": steps or [],
    }


def failed_step(name="Install dependencies"):
    return {
        "name": name,
        "conclusion": "failure",
        "started_at": "2026-09-17T01:00:30Z",
        "completed_at": "2026-09-17T01:01:30Z",
    }


def network_log():
    return (
        "2026-09-17T01:00:31.0000000Z ##[group]Run npm ci\n"
        "2026-09-17T01:00:45.0000000Z npm ERR! code ETIMEDOUT\n"
        "2026-09-17T01:00:46.0000000Z Error: connection reset by peer\n"
        "2026-09-17T01:00:47.0000000Z Process completed with exit code 1\n"
    )


def test_mixed_failures_only_select_transient_job():
    transient = assess_job(
        fake_job(1, "install deps", [failed_step()]),
        network_log(),
    )
    code = assess_job(fake_job(2, "lint"), "AssertionError\nTests failed\nProcess completed with exit code 1")

    safe, blocked = selective_plan([transient, code], run_attempt=1, max_attempts=2)

    assert [job.job_id for job in safe] == [1]
    assert [item.assessment.job_id for item in blocked] == [2]


def test_side_effect_job_is_blocked_even_when_transient():
    deploy = assess_job(
        fake_job(3, "deploy production", [failed_step("Deploy production")]),
        network_log(),
    )
    safe, blocked = selective_plan([deploy], run_attempt=1, max_attempts=2)

    assert safe == []
    assert len(blocked) == 1
    assert "side-effect" in blocked[0].reason


def test_attempt_cap_blocks_all_candidates():
    transient = assess_job(
        fake_job(4, "install deps", [failed_step()]),
        network_log(),
    )
    safe, blocked = selective_plan([transient], run_attempt=2, max_attempts=2)

    assert safe == []
    assert "max_attempts" in blocked[0].reason


def test_workflow_wide_side_effect_guard_blocks_safe_job():
    transient = assess_job(
        fake_job(5, "install deps", [failed_step()]),
        network_log(),
    )
    safe, blocked = selective_plan(
        [transient],
        run_attempt=1,
        max_attempts=2,
        workflow_side_effect_risk=True,
    )

    assert safe == []
    assert "dependent jobs" in blocked[0].reason


def test_selective_plan_blocks_high_confidence_transient_without_execution_provenance():
    transient = assess_job(
        fake_job(6, "install deps", [failed_step()]),
        "npm ERR! code ETIMEDOUT\nError: connection reset by peer\n",
    )
    assert transient.confidence == "high"
    assert transient.provenance_status == PROVENANCE_UNAVAILABLE

    safe, blocked = selective_plan([transient], run_attempt=1, max_attempts=2)

    assert safe == []
    assert len(blocked) == 1
    assert "provenance" in blocked[0].reason.lower()


def test_selective_plan_accepts_confirmed_execution_provenance():
    transient = assess_job(
        fake_job(7, "install deps", [failed_step()]),
        network_log(),
    )
    assert transient.provenance_status == PROVENANCE_CONFIRMED

    safe, blocked = selective_plan([transient], run_attempt=1, max_attempts=2)

    assert [item.job_id for item in safe] == [7]
    assert blocked == []



class _SelectiveBindingAPI:
    def __init__(self, run, jobs):
        self.run = run
        self.jobs = jobs
        self.get_run_calls = 0
        self.get_jobs_calls = 0

    def get_run(self, repo, run_id):
        self.get_run_calls += 1
        return self.run

    def get_jobs(self, repo, run_id):
        self.get_jobs_calls += 1
        return self.jobs


def _selective_run(attempt=1, status="completed", conclusion="failure"):
    return {
        "run_attempt": attempt,
        "head_sha": "abc123",
        "workflow_id": 99,
        "status": status,
        "conclusion": conclusion,
    }


def _live_failed_job(job_id, name="install deps"):
    return {
        "id": job_id,
        "name": name,
        "conclusion": "failure",
        "started_at": "2026-09-17T01:00:00Z",
        "completed_at": "2026-09-17T01:02:00Z",
    }


def _safe_transient(job_id, name="install deps"):
    return assess_job(
        fake_job(job_id, name, [failed_step()]),
        network_log(),
    )


def test_selective_subject_binding_allows_unchanged_job_execution():
    expected_run = _selective_run()
    expected_job = _live_failed_job(21)
    api = _SelectiveBindingAPI(expected_run.copy(), [expected_job.copy()])

    valid, reason = revalidate_selective_job_binding(
        api,
        "owner/repo",
        123,
        expected_run,
        expected_job,
    )

    assert valid is True
    assert "SELECTIVE_SCOPE_CONFIRMED" in reason
    assert api.get_run_calls == 1
    assert api.get_jobs_calls == 1


def test_selective_subject_binding_blocks_run_attempt_drift():
    expected_run = _selective_run(attempt=1)
    expected_job = _live_failed_job(22)
    api = _SelectiveBindingAPI(
        _selective_run(attempt=2),
        [expected_job.copy()],
    )

    valid, reason = revalidate_selective_job_binding(
        api,
        "owner/repo",
        123,
        expected_run,
        expected_job,
    )

    assert valid is False
    assert "SELECTIVE_SCOPE_CHANGED" in reason
    assert "run_attempt 1->2" in reason


def test_selective_subject_binding_blocks_when_target_job_execution_changes():
    expected_run = _selective_run()
    expected_job = _live_failed_job(23)
    changed_job = expected_job.copy()
    changed_job["completed_at"] = "2026-09-17T01:03:00Z"
    api = _SelectiveBindingAPI(expected_run.copy(), [changed_job])

    valid, reason = revalidate_selective_job_binding(
        api,
        "owner/repo",
        123,
        expected_run,
        expected_job,
    )

    assert valid is False
    assert "SELECTIVE_SCOPE_CHANGED" in reason
    assert "no longer matches the failed execution" in reason


def test_selective_epoch_performs_only_one_state_bound_mutation():
    expected_run = _selective_run()
    failed_jobs = [
        _live_failed_job(31, "install-a"),
        _live_failed_job(32, "install-b"),
    ]
    api = _SelectiveBindingAPI(
        expected_run.copy(),
        [job.copy() for job in failed_jobs],
    )
    safe = [
        _safe_transient(32, "install-b"),
        _safe_transient(31, "install-a"),
    ]
    rerun_calls = []

    def fake_rerun(api, repo, job_id):
        rerun_calls.append((repo, job_id))

    triggered, blocked = execute_selective_epoch(
        api,
        "owner/repo",
        123,
        expected_run,
        failed_jobs,
        safe,
        rerun_job=fake_rerun,
    )

    assert [item.job_id for item in triggered] == [31]
    assert rerun_calls == [("owner/repo", 31)]
    assert [item.assessment.job_id for item in blocked] == [32]
    assert "SELECTIVE_STATE_EPOCH_ENDED" in blocked[0].reason


def test_selective_epoch_does_not_mutate_after_binding_drift():
    expected_run = _selective_run(attempt=1)
    failed_jobs = [_live_failed_job(41)]
    api = _SelectiveBindingAPI(
        _selective_run(attempt=2),
        [failed_jobs[0].copy()],
    )
    safe = [_safe_transient(41)]
    rerun_calls = []

    def fake_rerun(api, repo, job_id):
        rerun_calls.append(job_id)

    triggered, blocked = execute_selective_epoch(
        api,
        "owner/repo",
        123,
        expected_run,
        failed_jobs,
        safe,
        rerun_job=fake_rerun,
    )

    assert triggered == []
    assert rerun_calls == []
    assert len(blocked) == 1
    assert "SELECTIVE_SCOPE_CHANGED" in blocked[0].reason
