from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ci_retry_gate import (
    CAUSAL,
    FAILURE_CONCLUSIONS,
    causal_evidence_role,
    classify_log,
)
from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    assess_mechanism_causality,
)
from transient_mechanism_gate import REASON_SERVER_5XX, detect_transient_mechanisms


DOMINANCE_CANDIDATE = "DOMINANCE_CANDIDATE"
DOMINANCE_NOT_APPLICABLE = "DOMINANCE_NOT_APPLICABLE"
DOMINANCE_NO_CAUSAL_SERVER_5XX = "DOMINANCE_NO_CAUSAL_SERVER_5XX"
DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE = "DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE"
DOMINANCE_ORDERING_UNPROVEN = "DOMINANCE_ORDERING_UNPROVEN"

_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
)
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# These are downstream wrappers that can be emitted because an invoked process
# failed for some other reason. They are not treated as primary code evidence.
_DOWNSTREAM_WRAPPER_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\btest failed, to rerun pass\b",
        r"\btests? failed\b",
        r"\bfailing tests?\b",
        r"\btest failure\b",
        r"\bassertion failed:\s*status\.success\(\)",
        r"\bprocess completed with exit code [1-9][0-9]*\b",
        r"\bcommand failed with exit code [1-9][0-9]*\b",
        r"\belifecycle\b.*\bcommand failed\b",
    ]
)

# Strong deterministic evidence that should prevent a transient cause from
# dominating merely because it appeared first.
_PRIMARY_DETERMINISTIC_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bsyntaxerror\b",
        r"\btypeerror\b",
        r"\breferenceerror\b",
        r"\bcompile error\b",
        r"\bcompilation failed\b",
        r"\bassertionerror\b",
        r"\bassertion failed\b",
    ]
)


@dataclass(frozen=True)
class CausalDominanceAssessment:
    status: str
    baseline_category: str
    proposed_category: str = ""
    failed_step: str = ""
    transient_evidence: tuple[str, ...] = ()
    downstream_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()

    @property
    def candidate(self) -> bool:
        return self.status == DOMINANCE_CANDIDATE


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _line_timestamp(raw_line: str) -> datetime | None:
    match = _TIMESTAMP_RE.match(raw_line)
    if not match:
        return None
    return _parse_time(match.group("timestamp"))


def _clean_line(raw_line: str) -> str:
    value = _TIMESTAMP_RE.sub("", raw_line)
    value = _ANSI_RE.sub("", value)
    return value.strip()


def _failed_step_window(job: dict) -> tuple[str, datetime, datetime] | None:
    failed_steps = [
        step
        for step in (job.get("steps") or [])
        if str(step.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]
    if len(failed_steps) != 1:
        return None
    step = failed_steps[0]
    name = str(step.get("name") or "").strip()
    start = _parse_time(step.get("started_at"))
    end = _parse_time(step.get("completed_at"))
    if not name or start is None or end is None or end < start:
        return None
    return name, start - timedelta(seconds=2), end + timedelta(seconds=2)


def assess_causal_dominance(job: dict, log_text: str) -> CausalDominanceAssessment:
    """Research-only precedence check for causal transient mechanisms.

    The hypothesis is intentionally narrow: when the runtime classifier says
    CODE_REGRESSION or FLAKY_TEST, but a causal SERVER_5XX occurs first inside
    the single failed step and every later deterministic signal is merely a
    generic failure wrapper, the upstream transient mechanism may be the better
    root-cause category.

    This function does not change classify_log(), retry authority, or policy.
    """
    baseline = classify_log(log_text)
    if baseline.category not in {"CODE_REGRESSION", "FLAKY_TEST"}:
        return CausalDominanceAssessment(
            DOMINANCE_NOT_APPLICABLE,
            baseline_category=baseline.category,
        )

    mechanism = assess_mechanism_causality(job, log_text)
    if (
        mechanism.status != MECHANISM_CAUSAL_CONFIRMED
        or REASON_SERVER_5XX not in mechanism.reasons
    ):
        return CausalDominanceAssessment(
            DOMINANCE_NO_CAUSAL_SERVER_5XX,
            baseline_category=baseline.category,
            failed_step=mechanism.failed_step,
        )

    window = _failed_step_window(job)
    if window is None:
        return CausalDominanceAssessment(
            DOMINANCE_ORDERING_UNPROVEN,
            baseline_category=baseline.category,
            failed_step=mechanism.failed_step,
        )
    failed_step, lower, upper = window

    transient: list[tuple[datetime, str]] = []
    wrapper: list[tuple[datetime, str]] = []
    primary: list[tuple[datetime, str]] = []

    for raw_line in log_text.splitlines():
        timestamp = _line_timestamp(raw_line)
        if timestamp is None or timestamp < lower or timestamp > upper:
            continue
        cleaned = _clean_line(raw_line)
        if not cleaned:
            continue

        if causal_evidence_role(raw_line) == CAUSAL:
            reasons, _matches = detect_transient_mechanisms(cleaned)
            if REASON_SERVER_5XX in reasons:
                transient.append((timestamp, cleaned))

        if any(pattern.search(cleaned) for pattern in _DOWNSTREAM_WRAPPER_PATTERNS):
            wrapper.append((timestamp, cleaned))
            continue

        if any(pattern.search(cleaned) for pattern in _PRIMARY_DETERMINISTIC_PATTERNS):
            primary.append((timestamp, cleaned))

    if not transient:
        return CausalDominanceAssessment(
            DOMINANCE_NO_CAUSAL_SERVER_5XX,
            baseline_category=baseline.category,
            failed_step=failed_step,
        )

    first_transient = min(item[0] for item in transient)

    # Any genuine deterministic evidence, whether before or after the transient
    # signal, blocks dominance. The current research question is only whether
    # generic wrappers are drowning out a clear upstream network failure.
    if primary:
        return CausalDominanceAssessment(
            DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
            baseline_category=baseline.category,
            failed_step=failed_step,
            transient_evidence=tuple(line for _ts, line in transient[:3]),
            blocking_evidence=tuple(line for _ts, line in primary[:3]),
        )

    downstream = [
        (ts, line) for ts, line in wrapper
        if ts >= first_transient
    ]
    earlier_wrapper = [
        (ts, line) for ts, line in wrapper
        if ts < first_transient
    ]
    if not downstream or earlier_wrapper:
        return CausalDominanceAssessment(
            DOMINANCE_ORDERING_UNPROVEN,
            baseline_category=baseline.category,
            failed_step=failed_step,
            transient_evidence=tuple(line for _ts, line in transient[:3]),
            downstream_evidence=tuple(line for _ts, line in downstream[:3]),
            blocking_evidence=tuple(line for _ts, line in earlier_wrapper[:3]),
        )

    return CausalDominanceAssessment(
        DOMINANCE_CANDIDATE,
        baseline_category=baseline.category,
        proposed_category="DEPENDENCY_NETWORK",
        failed_step=failed_step,
        transient_evidence=tuple(line for _ts, line in transient[:3]),
        downstream_evidence=tuple(line for _ts, line in downstream[:3]),
    )
