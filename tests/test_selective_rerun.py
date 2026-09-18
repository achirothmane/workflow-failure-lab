from ci_retry_gate import PROVENANCE_CONFIRMED, PROVENANCE_UNAVAILABLE, assess_job
from selective_rerun import selective_plan


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

