from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from xml.etree import ElementTree as ET

PASS = "pass"
FAIL = "fail"

QUARANTINE_CANDIDATE = "QUARANTINE_CANDIDATE"
INVESTIGATE = "INVESTIGATE"
DO_NOT_QUARANTINE = "DO_NOT_QUARANTINE"

MIN_QUARANTINE_RECOVERIES = 2


@dataclass(frozen=True)
class CaseObservation:
    test_id: str
    sha: str
    run_id: int
    attempt: int
    status: str
    duration_seconds: float
    job_name: str = "tests"


@dataclass(frozen=True)
class FlakyTestSummary:
    test_id: str
    observations: int
    failures: int
    passes: int
    same_sha_flips: int
    validated_recoveries: int
    persistent_failure_shas: int
    failed_seconds: float
    recovery_seconds: float
    estimated_waste_seconds: float
    recommendation: str
    reason: str

    @property
    def failure_rate(self) -> float:
        if self.observations <= 0:
            return 0.0
        return self.failures / self.observations

    @property
    def estimated_waste_minutes(self) -> float:
        return self.estimated_waste_seconds / 60.0


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def observations_from_junit(
    xml_text: str,
    *,
    sha: str,
    run_id: int,
    attempt: int = 1,
    job_name: str = "tests",
) -> list[CaseObservation]:
    """Convert JUnit XML into test-level observations.

    Skipped tests are excluded because they do not provide pass/fail evidence.
    The parser accepts common testsuite and testsuites layouts and ignores XML namespaces.
    """
    if not sha.strip():
        raise ValueError("sha must be non-empty")
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    if attempt <= 0:
        raise ValueError("attempt must be positive")

    root = ET.fromstring(xml_text)
    observations: list[CaseObservation] = []

    for case in root.iter():
        if _local_name(case.tag) != "testcase":
            continue

        name = str(case.attrib.get("name") or "").strip()
        if not name:
            continue

        classname = str(case.attrib.get("classname") or "").strip()
        test_id = f"{classname}::{name}" if classname else name

        skipped = False
        failed = False
        for child in list(case):
            child_name = _local_name(child.tag)
            if child_name == "skipped":
                skipped = True
                break
            if child_name in {"failure", "error"}:
                failed = True

        if skipped:
            continue

        raw_duration = str(case.attrib.get("time") or "0").strip()
        try:
            duration = max(float(raw_duration), 0.0)
        except ValueError:
            duration = 0.0

        observations.append(
            CaseObservation(
                test_id=test_id,
                sha=sha,
                run_id=run_id,
                attempt=attempt,
                status=FAIL if failed else PASS,
                duration_seconds=duration,
                job_name=job_name,
            )
        )

    return observations


def _validate_observation(item: CaseObservation) -> None:
    if not item.test_id.strip():
        raise ValueError("test_id must be non-empty")
    if not item.sha.strip():
        raise ValueError("sha must be non-empty")
    if item.run_id <= 0:
        raise ValueError("run_id must be positive")
    if item.attempt <= 0:
        raise ValueError("attempt must be positive")
    if item.status not in {PASS, FAIL}:
        raise ValueError(f"unsupported status: {item.status!r}")
    if item.duration_seconds < 0:
        raise ValueError("duration_seconds must be non-negative")


def _same_sha_evidence(
    items: list[CaseObservation],
) -> tuple[int, int, int, float]:
    by_sha: dict[str, list[CaseObservation]] = defaultdict(list)
    for item in items:
        by_sha[item.sha].append(item)

    flips = 0
    validated_recoveries = 0
    persistent_failure_shas = 0
    recovery_seconds = 0.0

    for sha_items in by_sha.values():
        ordered = sorted(sha_items, key=lambda item: (item.run_id, item.attempt))
        first_failure_index = next(
            (index for index, item in enumerate(ordered) if item.status == FAIL),
            None,
        )
        if first_failure_index is None:
            continue

        first_failure = ordered[first_failure_index]
        failure_execution = (first_failure.run_id, first_failure.attempt)
        later_pass = next(
            (
                item
                for item in ordered[first_failure_index + 1 :]
                if item.status == PASS
                and (item.run_id, item.attempt) > failure_execution
            ),
            None,
        )
        if later_pass is not None:
            flips += 1
            validated_recoveries += 1
            recovery_seconds += later_pass.duration_seconds
        else:
            persistent_failure_shas += 1

    return (
        flips,
        validated_recoveries,
        persistent_failure_shas,
        recovery_seconds,
    )


def _recommend(
    *,
    failures: int,
    validated_recoveries: int,
    persistent_failure_shas: int,
) -> tuple[str, str]:
    if persistent_failure_shas > 0:
        return (
            DO_NOT_QUARANTINE,
            (
                f"{persistent_failure_shas} code revision(s) contain a failure "
                "without a same-revision recovery; quarantine could hide a real regression."
            ),
        )

    if (
        validated_recoveries >= MIN_QUARANTINE_RECOVERIES
        and failures >= 2
    ):
        return (
            QUARANTINE_CANDIDATE,
            (
                f"{validated_recoveries} same-revision fail→pass recoveries were observed "
                "with no persistent-failure revision. Recommend human-reviewed temporary "
                "quarantine, not automatic quarantine."
            ),
        )

    if validated_recoveries > 0:
        return (
            INVESTIGATE,
            (
                f"Only {validated_recoveries} same-revision fail→pass recovery was observed; "
                f"at least {MIN_QUARANTINE_RECOVERIES} are required before recommending quarantine."
            ),
        )

    return (
        DO_NOT_QUARANTINE,
        "No same-revision fail→pass recovery was observed.",
    )


def summarize_flaky_tests(
    observations: list[CaseObservation],
) -> tuple[FlakyTestSummary, ...]:
    """Rank tests by estimated CI waste using conservative flake evidence."""
    grouped: dict[str, list[CaseObservation]] = defaultdict(list)
    for item in observations:
        _validate_observation(item)
        grouped[item.test_id].append(item)

    summaries: list[FlakyTestSummary] = []
    for test_id, items in grouped.items():
        failures = sum(item.status == FAIL for item in items)
        passes = sum(item.status == PASS for item in items)
        failed_seconds = sum(
            item.duration_seconds
            for item in items
            if item.status == FAIL
        )
        (
            same_sha_flips,
            validated_recoveries,
            persistent_failure_shas,
            recovery_seconds,
        ) = _same_sha_evidence(items)
        recommendation, reason = _recommend(
            failures=failures,
            validated_recoveries=validated_recoveries,
            persistent_failure_shas=persistent_failure_shas,
        )

        summaries.append(
            FlakyTestSummary(
                test_id=test_id,
                observations=len(items),
                failures=failures,
                passes=passes,
                same_sha_flips=same_sha_flips,
                validated_recoveries=validated_recoveries,
                persistent_failure_shas=persistent_failure_shas,
                failed_seconds=round(failed_seconds, 3),
                recovery_seconds=round(recovery_seconds, 3),
                estimated_waste_seconds=round(
                    failed_seconds + recovery_seconds,
                    3,
                ),
                recommendation=recommendation,
                reason=reason,
            )
        )

    summaries.sort(
        key=lambda item: (
            -item.estimated_waste_seconds,
            -item.validated_recoveries,
            -item.failures,
            item.test_id,
        )
    )
    return tuple(summaries)
