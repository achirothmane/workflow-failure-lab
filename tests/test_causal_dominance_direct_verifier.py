from causal_dominance_direct_verifier import (
    DIRECT_REJECTED,
    DIRECT_UNRESOLVED,
    DIRECT_VERIFIED,
    PIPX_FAILURE_ATTEMPT,
    PIPX_JOB_NAMES,
    PIPX_RECOVERY_ATTEMPT,
    PIPX_REPOSITORY,
    PIPX_RUN_ID,
    render_pipx_direct_verification,
    verify_pipx_run,
)


def _job(job_id, name, conclusion):
    return {
        "id": job_id,
        "name": name,
        "conclusion": conclusion,
        "steps": [
            {
                "name": "🏃 Run test suite",
                "conclusion": conclusion,
                "started_at": "2026-08-12T16:43:00Z",
                "completed_at": "2026-08-12T16:52:00Z",
            }
        ],
    }


def _pipx_log():
    return (
        "2026-08-12T16:51:50.5334104Z >           assert f\"installed package {package_name}\" in captured.out\n"
        "2026-08-12T16:51:50.5340468Z tests/test_install.py:56: AssertionError\n"
        "2026-08-12T16:51:50.5365640Z >       assert not run_pipx_cli([\"install\", "
        "\"https://github.com/wntrblm/nox/archive/2022.1.7.zip\"])\n"
        "2026-08-12T16:51:50.5373742Z ERROR: Could not install packages due to an OSError: "
        "HTTPSConnectionPool(host='github.com', port=443): Max retries exceeded with url: "
        "/wntrblm/nox/archive/2022.1.7.zip "
        "(Caused by ResponseError('too many 503 error responses'))\n"
        "2026-08-12T16:51:50.6885484Z ##[error]Process completed with exit code 1.\n"
    )


class FakeAPI:
    def __init__(self, *, include_rerun=True, network=True):
        self.include_rerun = include_rerun
        self.network = network

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        assert method == "GET"
        if f"/attempts/{PIPX_FAILURE_ATTEMPT}/jobs" in path:
            return {
                "jobs": [
                    _job(1001, PIPX_JOB_NAMES[0], "failure"),
                    _job(1002, PIPX_JOB_NAMES[1], "failure"),
                ]
            }
        if f"/attempts/{PIPX_RECOVERY_ATTEMPT}/jobs" in path:
            if not self.include_rerun:
                return {"jobs": []}
            return {
                "jobs": [
                    _job(2001, PIPX_JOB_NAMES[0], "success"),
                    _job(2002, PIPX_JOB_NAMES[1], "success"),
                ]
            }
        raise AssertionError(path)

    def get_job_logs(self, repo, job_id):
        assert repo == PIPX_REPOSITORY
        if self.network:
            return _pipx_log()
        return (
            "2026-08-12T16:51:50.5340468Z tests/test_install.py:56: AssertionError\n"
            "2026-08-12T16:51:50.6885484Z ##[error]Process completed with exit code 1.\n"
        )


def test_pipx_direct_verifier_accepts_structural_network_cause():
    summary = verify_pipx_run(FakeAPI())

    assert len(summary.records) == 2
    assert len(summary.verified_jobs) == 2
    assert summary.independent_verified_runs == 1
    assert summary.unresolved == 0
    assert all(item.status == DIRECT_VERIFIED for item in summary.records)
    assert all(item.has_503_root_cause for item in summary.records)
    assert all(item.has_downstream_assertion_shape for item in summary.records)


def test_pipx_direct_verifier_rejects_assertion_without_503_root_cause():
    summary = verify_pipx_run(FakeAPI(network=False))

    assert len(summary.verified_jobs) == 0
    assert all(item.status == DIRECT_REJECTED for item in summary.records)


def test_pipx_direct_verifier_fails_closed_when_rerun_missing():
    summary = verify_pipx_run(FakeAPI(include_rerun=False))

    assert summary.unresolved == 2
    assert all(item.status == DIRECT_UNRESOLVED for item in summary.records)


def test_pipx_direct_report_counts_one_independent_run():
    report = render_pipx_direct_verification(verify_pipx_run(FakeAPI()))

    assert f"{PIPX_REPOSITORY} #{PIPX_RUN_ID}" in report
    assert "Directly verified jobs: **2**" in report
    assert "Independent verified runs contributed: **1**" in report
    assert "generic deterministic blocker" in report.lower()
