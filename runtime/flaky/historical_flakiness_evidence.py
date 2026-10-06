"""Policy-free historical flaky-test evidence for the current CI failure.

This producer converts the existing JUnit history analysis into a bounded evidence
contract that can later be fused with CI Retry Gate evidence. It deliberately does
not decide whether a rerun is safe and it does not mutate CI state.
"""

from __future__ import annotations

from collections import Counter
from typing import Protocol

from runtime.flaky.flaky_test_intelligence import (
    FAIL,
    CaseObservation,
    FlakyTestSummary,
    summarize_flaky_tests,
)


HISTORICAL_FLAKINESS_EVIDENCE_SCHEMA = "historical-flakiness-evidence.ci.v1"


class FlakyHistoryResultLike(Protocol):
    runs_scanned: int
    artifacts_seen: int
    artifacts_analyzed: int
    artifacts_skipped_ambiguous: int
    xml_files_analyzed: int
    observations: int
    summaries: tuple[FlakyTestSummary, ...]
    case_observations: tuple[CaseObservation, ...]


def _summary_payload(summary: FlakyTestSummary | None) -> dict | None:
    if summary is None:
        return None
    return {
        "observations": summary.observations,
        "failures": summary.failures,
        "passes": summary.passes,
        "failure_rate": round(summary.failure_rate, 6),
        "same_sha_flips": summary.same_sha_flips,
        "validated_recoveries": summary.validated_recoveries,
        "persistent_failure_shas": summary.persistent_failure_shas,
        "failed_seconds": summary.failed_seconds,
        "recovery_seconds": summary.recovery_seconds,
        "estimated_waste_seconds": summary.estimated_waste_seconds,
    }


def _other_execution_summary(
    observations: tuple[CaseObservation, ...],
    *,
    test_id: str,
    run_id: int,
    run_attempt: int,
) -> FlakyTestSummary | None:
    """Summarize executions other than the exact subject execution.

    This is intentionally named "other execution", not "prior history": CaseObservation
    v1 does not carry a trusted execution timestamp. A later consumer must not treat
    these observations as temporally prior evidence unless it can prove ordering.
    """

    other = [
        item
        for item in observations
        if item.test_id == test_id
        and (item.run_id, item.attempt) != (run_id, run_attempt)
    ]
    if not other:
        return None
    return summarize_flaky_tests(other)[0]


def produce_historical_flakiness_evidence(
    *,
    repo: str,
    current_run: dict,
    run_id: int,
    run_attempt: int,
    result: FlakyHistoryResultLike,
) -> dict:
    """Return test-history facts relevant to failures in the exact current execution.

    The contract is bounded to tests that are observed failing in the subject
    run/attempt. It contains no quarantine recommendation and no rerun authorization.
    """

    if not repo.strip():
        raise ValueError("repo must be non-empty")
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    if run_attempt <= 0:
        raise ValueError("run_attempt must be positive")

    current_failures: dict[str, list[CaseObservation]] = {}
    for item in result.case_observations:
        if (
            item.run_id == run_id
            and item.attempt == run_attempt
            and item.status == FAIL
        ):
            current_failures.setdefault(item.test_id, []).append(item)

    summaries = {item.test_id: item for item in result.summaries}
    tests: list[dict] = []
    missing_sources: list[str] = []

    if not current_failures:
        missing_sources.append("current_failed_test_observations")

    for test_id in sorted(current_failures):
        current_items = current_failures[test_id]
        summary = summaries.get(test_id)
        other_summary = _other_execution_summary(
            result.case_observations,
            test_id=test_id,
            run_id=run_id,
            run_attempt=run_attempt,
        )
        if summary is None:
            missing_sources.append(f"test:{test_id}:summary")
        if other_summary is None:
            missing_sources.append(f"test:{test_id}:other-executions")

        all_items = [
            item for item in result.case_observations if item.test_id == test_id
        ]
        failure_jobs = Counter(
            item.job_name
            for item in all_items
            if item.status == FAIL and item.job_name
        )
        source_files = sorted(
            {
                item.source_file
                for item in all_items
                if item.source_file
            }
        )

        tests.append(
            {
                "test_id": test_id,
                "current_execution": {
                    "status": FAIL,
                    "failure_observations": len(current_items),
                    "job_names": sorted(
                        {item.job_name for item in current_items if item.job_name}
                    ),
                    "source_files": sorted(
                        {item.source_file for item in current_items if item.source_file}
                    ),
                },
                "collected_history": _summary_payload(summary),
                "other_execution_evidence": _summary_payload(other_summary),
                "failure_job_distribution": [
                    {"job_name": name, "failures": count}
                    for name, count in sorted(
                        failure_jobs.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
                "source_files": source_files,
            }
        )

    missing_sources = sorted(set(missing_sources))

    return {
        "schema_version": HISTORICAL_FLAKINESS_EVIDENCE_SCHEMA,
        "producer": {
            "name": "workflow-failure-lab",
            "component": "historical_flakiness",
            "mode": "deterministic",
            "policy_free": True,
        },
        "subject": {
            "type": "ci_workflow_run_attempt",
            "repository": repo,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "head_sha": str(current_run.get("head_sha") or ""),
            "workflow_id": current_run.get("workflow_id"),
        },
        "collection": {
            "runs_scanned": result.runs_scanned,
            "artifacts_seen": result.artifacts_seen,
            "artifacts_analyzed": result.artifacts_analyzed,
            "artifacts_skipped_ambiguous": result.artifacts_skipped_ambiguous,
            "xml_files_analyzed": result.xml_files_analyzed,
            "observations": result.observations,
            "history_includes_subject_execution": True,
            "temporal_ordering_proven": False,
        },
        "tests": tests,
        "quality": {
            "status": "COMPLETE" if not missing_sources else "PARTIAL",
            "missing_sources": missing_sources,
            "contradictions": [],
        },
    }
