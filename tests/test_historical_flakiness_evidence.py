from __future__ import annotations

from flaky_test_history import FlakyHistoryResult
from runtime.flaky.flaky_test_intelligence import (
    FAIL,
    PASS,
    CaseObservation,
    summarize_flaky_tests,
)
from runtime.flaky.historical_flakiness_evidence import (
    HISTORICAL_FLAKINESS_EVIDENCE_SCHEMA,
    produce_historical_flakiness_evidence,
)


def _obs(
    test_id: str,
    sha: str,
    run_id: int,
    attempt: int,
    status: str,
    *,
    job_name: str = "junit-linux",
    source_file: str = "tests/test_cart.py",
) -> CaseObservation:
    return CaseObservation(
        test_id=test_id,
        sha=sha,
        run_id=run_id,
        attempt=attempt,
        status=status,
        duration_seconds=1.0,
        job_name=job_name,
        source_file=source_file,
    )


def _result(items: list[CaseObservation]) -> FlakyHistoryResult:
    return FlakyHistoryResult(
        runs_scanned=4,
        artifacts_seen=5,
        artifacts_analyzed=5,
        artifacts_skipped_ambiguous=0,
        xml_files_analyzed=5,
        observations=len(items),
        summaries=summarize_flaky_tests(items),
        case_observations=tuple(items),
    )


def _contains_key(value: object, forbidden: str) -> bool:
    if isinstance(value, dict):
        return forbidden in value or any(
            _contains_key(item, forbidden) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def test_producer_is_bounded_to_exact_current_failed_tests_and_policy_free() -> None:
    items = [
        _obs("pkg.TestCart::test_total", "sha-old", 10, 1, FAIL),
        _obs("pkg.TestCart::test_total", "sha-old", 10, 2, PASS),
        _obs(
            "pkg.TestCart::test_total",
            "sha-current",
            20,
            1,
            FAIL,
            job_name="junit-windows",
        ),
        _obs("pkg.TestOther::test_ok", "sha-current", 20, 1, PASS),
    ]

    evidence = produce_historical_flakiness_evidence(
        repo="owner/repo",
        current_run={"head_sha": "sha-current", "workflow_id": 7},
        run_id=20,
        run_attempt=1,
        result=_result(items),
    )

    assert evidence["schema_version"] == HISTORICAL_FLAKINESS_EVIDENCE_SCHEMA
    assert evidence["producer"]["policy_free"] is True
    assert evidence["subject"]["run_id"] == 20
    assert evidence["subject"]["run_attempt"] == 1
    assert [item["test_id"] for item in evidence["tests"]] == [
        "pkg.TestCart::test_total"
    ]
    assert evidence["tests"][0]["current_execution"]["job_names"] == [
        "junit-windows"
    ]
    assert evidence["tests"][0]["other_execution_evidence"]["validated_recoveries"] == 1

    for forbidden in ("decision", "retry_permitted", "max_attempts", "recommendation"):
        assert not _contains_key(evidence, forbidden)


def test_failure_job_distribution_is_deterministic_and_evidence_only() -> None:
    items = [
        _obs("test_x", "a", 1, 1, FAIL, job_name="windows"),
        _obs("test_x", "a", 1, 2, PASS, job_name="windows"),
        _obs("test_x", "b", 2, 1, FAIL, job_name="windows"),
        _obs("test_x", "b", 2, 2, PASS, job_name="windows"),
        _obs("test_x", "c", 3, 1, FAIL, job_name="macos"),
    ]

    evidence = produce_historical_flakiness_evidence(
        repo="owner/repo",
        current_run={"head_sha": "c", "workflow_id": 7},
        run_id=3,
        run_attempt=1,
        result=_result(items),
    )

    assert evidence["tests"][0]["failure_job_distribution"] == [
        {"job_name": "windows", "failures": 2},
        {"job_name": "macos", "failures": 1},
    ]
    assert evidence["collection"]["temporal_ordering_proven"] is False


def test_missing_current_failure_stays_explicit_and_partial() -> None:
    items = [_obs("test_x", "a", 1, 1, PASS)]

    evidence = produce_historical_flakiness_evidence(
        repo="owner/repo",
        current_run={"head_sha": "a", "workflow_id": 7},
        run_id=1,
        run_attempt=1,
        result=_result(items),
    )

    assert evidence["tests"] == []
    assert evidence["quality"]["status"] == "PARTIAL"
    assert "current_failed_test_observations" in evidence["quality"]["missing_sources"]


def test_exact_attempt_binding_does_not_confuse_rerun_observations() -> None:
    items = [
        _obs("test_x", "same-sha", 9, 1, FAIL),
        _obs("test_x", "same-sha", 9, 2, PASS),
    ]

    evidence = produce_historical_flakiness_evidence(
        repo="owner/repo",
        current_run={"head_sha": "same-sha", "workflow_id": 7},
        run_id=9,
        run_attempt=1,
        result=_result(items),
    )

    assert len(evidence["tests"]) == 1
    assert evidence["tests"][0]["current_execution"]["status"] == FAIL
    assert evidence["tests"][0]["other_execution_evidence"]["passes"] == 1
    assert evidence["collection"]["history_includes_subject_execution"] is True
