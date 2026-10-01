from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from easl_state_binding import (
    StateBinding,
    StateBindingError,
    evaluate_required_state_bindings,
)
from evidence_artifact import write_evidence_artifact
from evidence_producer import produce_ci_evidence_bundle
from ci_assumption_profile import build_ci_retry_assumption_state
from ci_authority_profile import build_ci_authority_grant
from decision_experience import build_decision_experience, render_decision_card
from eba_integration_contract import (
    ContractViolation,
    build_ci_action_request,
    build_decision_artifact,
    build_execution_receipt,
    ensure_decision_allows_request,
    write_contract_artifact,
)

TRANSIENT_CATEGORIES = {"RUNNER_INFRA", "DEPENDENCY_NETWORK"}
FAILURE_CONCLUSIONS = {"failure", "timed_out"}


_SECRET_PATTERNS = [
    ("github_legacy_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("github_fine_grained_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "authorization_bearer",
        re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+\-/]+=*"),
    ),
    (
        "credential_assignment",
        re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+"),
    ),
]

# GitHub logs can contain terminal color/control sequences inside error lines.
# Strip them before matching so operational signatures are not split by escape bytes.
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_RUNNER_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+"
)

CAUSAL = "CAUSAL"
AMBIGUOUS = "AMBIGUOUS"
NON_CAUSAL = "NON_CAUSAL"

PROVENANCE_CONFIRMED = "CONFIRMED"
PROVENANCE_UNAVAILABLE = "UNAVAILABLE"
PROVENANCE_MISMATCH = "MISMATCH"
PROVENANCE_NOT_APPLICABLE = "NOT_APPLICABLE"

FAILURE_STEP_CONFIRMED = "FAILURE_STEP_CONFIRMED"
FAILURE_STEP_AMBIGUOUS = "FAILURE_STEP_AMBIGUOUS"
FAILURE_STEP_UNAVAILABLE = "FAILURE_STEP_UNAVAILABLE"

_RUNNER_TIMESTAMP_CAPTURE_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
)


# This path is used only when the ordinary job-log evidence is unavailable.
# Keep the accepted message narrow: GitHub Actions emits this annotation when
# the job's runner stops communicating with the service. The annotation is not
# treated as root-cause proof; it is an exact job/check-run-bound transient
# signal and still remains subject to side-effect and attempt gates.
_RUNNER_LOSS_CHECK_ANNOTATION_RE = re.compile(
    r"^The (?:hosted|self-hosted) runner"
    r"(?:\s*:\s*[^\r\n.]{1,160})?"
    r" lost communication with the server\.",
    re.IGNORECASE,
)

_NON_CAUSAL_LOG_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^##\[(?:group|endgroup|debug)\]",
        r":(?:ref|class|func|meth|doc|option):\\?`",
        r"^(?:print|printf|echo|assert|raise)\b.*(?:timeout|timed out|connection reset|could not resolve host)",
        r"^\*\s+\[new\s+(?:branch|tag)\]\s+",
        r"^[A-Za-z0-9_.-]+:\s*(?:error|warn|warning|ignore)$",
    ]
)

_CAUSAL_OPERATIONAL_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"^##\[error\]",
        r"^::error::",
        r"^(?:error|fatal|exception|panic)\b\s*[:!]",
        r"^npm (?:err!|error)\b",
        r"^(?:\[[^\]\r\n]{1,80}\]\s+)?curl:\s*\(\d+\)",
        r"^read tcp\b",
        r"^dial tcp\b",
        r"^traceback \(most recent call last\):",
        r"^process completed with exit code\b",
        r"\b_ssl\.c:\d+:\s*the handshake operation timed out\b",
        r"^http\s+(?:429|502|503|504)\b",
    ]
)

_CATEGORY_RULES: dict[str, tuple[tuple[int, re.Pattern[str]], ...]] = {
    "RUNNER_INFRA": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"lost communication with the server"),
            (5, r"runner .* (lost|stopped|shutdown|disconnected)"),
            (5, r"hosted runner .* (shutdown|unavailable|failed)"),
            (4, r"the runner has received a shutdown signal"),
            (4, r"failed to start (the )?(virtual machine|runner)"),
            (3, r"internal server error"),
            (3, r"service unavailable"),
        ]
    ),
    "DEPENDENCY_NETWORK": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"temporary failure in name resolution"),
            (5, r"could not resolve host"),
            (5, r"econnreset|etimedout|eai_again"),
            (4, r"connection reset by peer"),
            (4, r"tls handshake timeout"),
            (4, r"network is unreachable"),
            (3, r"\b429\b.*too many requests|too many requests.*\b429\b"),
            (3, r"\b502\b.*bad gateway|\b503\b.*service unavailable|\b504\b.*gateway timeout"),
            (2, r"connection timed out|read timed out|connect timeout"),
        ]
    ),
    "RESOURCE_TIMEOUT": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"process completed with exit code 137"),
            (5, r"out of memory|oomkilled|cannot allocate memory"),
            (4, r"no space left on device"),
            (3, r"exceeded.*time limit|job .* timed out|operation timed out"),
        ]
    ),
    "FLAKY_TEST": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"flaky test|test .* marked flaky"),
            (4, r"passed on retry|passed after retry"),
            (3, r"retrying test|rerun.*test"),
        ]
    ),
    "CODE_REGRESSION": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (4, r"assertionerror|assertion failed"),
            (4, r"syntaxerror|typeerror|referenceerror|compile error|compilation failed"),
            (3, r"tests? failed|failing tests?|test failure"),
            (3, r"lint(ing)? failed|type.?check.*failed"),
            (2, r"process completed with exit code [1-9][0-9]*"),
        ]
    ),
}

# A runner shutdown line is a terminal symptom, not independent proof that
# infrastructure caused the failure. Workload/resource behavior can surface as
# the same SIGTERM/exit-143 shutdown sequence, so this signal alone must never
# promote a retry to high confidence.
_RUNNER_TERMINAL_SYMPTOM_RULES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"the runner has received a shutdown signal",
        r"process completed with exit code 143",
    ]
)

# These signatures are intentionally narrower than the scoring rules above.
# A single occurrence may be enough for high confidence only when it looks like
# independent operational evidence emitted by the runner/network substrate,
# rather than prose, documentation, a source fixture, or a terminal symptom.
_HIGH_SPECIFICITY_TRANSIENT_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "RUNNER_INFRA": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"lost communication with the server",
            r"hosted runner .* (shutdown|unavailable|failed)",
        ]
    ),
    "DEPENDENCY_NETWORK": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\bnpm (?:err!|error) code (?:econnreset|etimedout|eai_again)\b",
            r"\bread tcp\b.*\bread:\s*connection reset by peer\b",
            r"\bdial tcp\b.*(?:i/o timeout|connect:\s*(?:connection timed out|network is unreachable|connection refused))",
            r"^(?:\[[^\]\r\n]{1,80}\]\s+)?curl:\s*\((?:6|7|28|35|56)\)(?:\s|$)",
            r"^(?:##\[error\].*|error:.*)\bunexpected status from "
            r"(?:head|get|post|put|delete) request to https?://\S+:\s*"
            r"(?:502 bad gateway|503 service unavailable|504 gateway timeout)",
            r"\bfatal: unable to access\b.*(?:could not resolve host|recv failure: connection reset by peer|failed to connect|operation timed out)",
            r"\b(?:error|fatal):\s*connection reset by peer\b",
            r"\bconnect etimedout\b",
            r"\btls handshake timeout\b",
        ]
    ),
}

_SIDE_EFFECT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bdeploy(?:ment|ing)?\b",
        r"\bpublish(?:ing)?\b",
        r"\brelease\b",
        r"\bterraform\s+apply\b",
        r"\bkubectl\s+apply\b",
        r"\bhelm\s+(upgrade|install)\b",
        r"\bmigrat(?:e|ion|ing)\b",
        r"\bdatabase\s+(write|update|seed)\b",
        r"\bpush\s+image\b",
        r"\bgit\s+push\b",
        r"\bpush(?:ing)?\s+branch\b",
        r"\bcreate\s+(?:a\s+)?pr\b",
        r"\bcreate\s+pull\s+request\b",
        r"\bnpm\s+publish\b",
        r"\bpypi\b",
    ]
)


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: str
    score: int
    evidence: tuple[str, ...]
    fields_redacted: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExecutionProvenance:
    status: str
    step_name: str = ""
    command: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class FailureStepProvenance:
    status: str
    step_name: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class JobAssessment:
    job_id: int
    name: str
    category: str
    confidence: str
    evidence: tuple[str, ...]
    provenance_status: str
    provenance_step: str
    provenance_command: str
    provenance_evidence: tuple[str, ...]
    failure_step_status: str
    failure_step: str
    failure_step_evidence: tuple[str, ...]
    side_effect_risk: bool
    side_effect_evidence: tuple[str, ...]
    duration_minutes: float
    masking_fields_redacted: tuple[str, ...] = ()


def redact_with_provenance(text: str) -> tuple[str, tuple[str, ...]]:
    """Redact credential material and report which masking rules matched."""
    value = text
    fields_redacted: set[str] = set()
    for field_name, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            fields_redacted.add(field_name)
        value = pattern.sub(
            lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]",
            value,
        )
    return value, tuple(sorted(fields_redacted))


def redact(text: str) -> str:
    return redact_with_provenance(text)[0]


def _useful_line(line: str) -> str:
    line = _ANSI_ESCAPE_RE.sub("", redact(line))
    line = _RUNNER_TIMESTAMP_RE.sub("", line).strip()
    if len(line) > 300:
        line = line[:297] + "..."
    return line


def causal_evidence_role(line: str) -> str:
    """Classify whether a cleaned log line is causal failure evidence or log noise."""
    cleaned = _useful_line(line)
    if not cleaned:
        return NON_CAUSAL

    if cleaned.startswith("#") and not cleaned.startswith("##[error]"):
        return NON_CAUSAL
    if any(pattern.search(cleaned) for pattern in _NON_CAUSAL_LOG_PATTERNS):
        return NON_CAUSAL
    if any(pattern.search(cleaned) for pattern in _CAUSAL_OPERATIONAL_PATTERNS):
        return CAUSAL
    return AMBIGUOUS


def classify_log(log_text: str) -> Classification:
    scores: dict[str, int] = {name: 0 for name in _CATEGORY_RULES}
    evidence: dict[str, list[str]] = {name: [] for name in _CATEGORY_RULES}
    strong_transient_evidence: dict[str, list[str]] = {
        name: [] for name in _HIGH_SPECIFICITY_TRANSIENT_RULES
    }
    runner_terminal_symptom = False

    seen_lines: set[str] = set()
    fields_redacted: set[str] = set()
    for raw_line in log_text.splitlines():
        redacted_line, redacted_fields = redact_with_provenance(raw_line)
        fields_redacted.update(redacted_fields)
        line = _useful_line(redacted_line)
        role = causal_evidence_role(line)
        if not line or role == NON_CAUSAL or line in seen_lines:
            continue
        seen_lines.add(line)

        if any(pattern.search(line) for pattern in _RUNNER_TERMINAL_SYMPTOM_RULES):
            runner_terminal_symptom = True

        for category, rules in _CATEGORY_RULES.items():
            for weight, pattern in rules:
                if pattern.search(line):
                    effective_weight = weight
                    # Weak transient phrases are easy to encounter in prose. If the
                    # line has no operational anchor, count them only as a hint.
                    if (
                        category in TRANSIENT_CATEGORIES
                        and role == AMBIGUOUS
                        and weight <= 2
                    ):
                        effective_weight = 1
                    scores[category] += effective_weight
                    if len(evidence[category]) < 3 and line not in evidence[category]:
                        evidence[category].append(line)
                    break

        for category, patterns in _HIGH_SPECIFICITY_TRANSIENT_RULES.items():
            if any(pattern.search(line) for pattern in patterns):
                if len(strong_transient_evidence[category]) < 3 and line not in strong_transient_evidence[category]:
                    strong_transient_evidence[category].append(line)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_category, top_score = ranked[0]
    second_score = ranked[1][1]

    if top_score < 3:
        return Classification(
            "UNKNOWN",
            "low",
            top_score,
            tuple(),
            tuple(sorted(fields_redacted)),
        )

    margin = top_score - second_score
    if top_score >= 7 and margin >= 3:
        confidence = "high"
    elif top_score >= 4 and margin >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    if (
        top_category in TRANSIENT_CATEGORIES
        and strong_transient_evidence.get(top_category)
        and second_score <= 2
    ):
        confidence = "high"

    if (
        top_category == "RUNNER_INFRA"
        and runner_terminal_symptom
        and not strong_transient_evidence.get("RUNNER_INFRA")
    ):
        confidence = "medium" if top_score >= 4 else "low"

    if top_category == "CODE_REGRESSION" and top_score < 7:
        confidence = "medium" if top_score >= 4 else "low"

    return Classification(
        top_category,
        confidence,
        top_score,
        tuple(evidence[top_category]),
        tuple(sorted(fields_redacted)),
    )


def _metadata_redacted_fields(job: dict) -> tuple[str, ...]:
    fields_redacted: set[str] = set()
    candidates = [str(job.get("name") or "")]
    candidates.extend(str(step.get("name") or "") for step in job.get("steps") or [])
    for candidate in candidates:
        _, matched = redact_with_provenance(candidate)
        fields_redacted.update(matched)
    return tuple(sorted(fields_redacted))


def detect_side_effect_risk(job: dict) -> tuple[bool, tuple[str, ...]]:
    hits: list[str] = []
    candidates = [str(job.get("name") or "")]
    for step in job.get("steps") or []:
        candidates.append(str(step.get("name") or ""))

    for candidate in candidates:
        for pattern in _SIDE_EFFECT_PATTERNS:
            if pattern.search(candidate):
                cleaned = _useful_line(candidate)
                if cleaned and cleaned not in hits:
                    hits.append(cleaned)
                break
    return bool(hits), tuple(hits[:3])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def job_duration_minutes(job: dict) -> float:
    start = _parse_time(job.get("started_at"))
    end = _parse_time(job.get("completed_at"))
    if start is None or end is None or end < start:
        return 0.0
    return round((end - start).total_seconds() / 60.0, 2)


def _raw_line_timestamp(raw_line: str) -> datetime | None:
    match = _RUNNER_TIMESTAMP_CAPTURE_RE.match(raw_line)
    if not match:
        return None
    return _parse_time(match.group("timestamp"))


def _step_command_in_window(log_text: str, start: datetime, end: datetime) -> str:
    for raw_line in log_text.splitlines():
        timestamp = _raw_line_timestamp(raw_line)
        if timestamp is None or timestamp < start or timestamp > end:
            continue
        cleaned = _useful_line(raw_line)
        match = re.match(r"^##\[group\]Run\s+(.+)$", cleaned, re.IGNORECASE)
        if match:
            return match.group(1).strip()[:220]
    return ""


def assess_failure_step_provenance(job: dict) -> FailureStepProvenance:
    """Identify the failed GitHub step for outcome validation only.

    This is intentionally independent from transient classification and does not
    grant rerun authority.
    """
    failed_steps = [
        step for step in (job.get("steps") or [])
        if str(step.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]
    if not failed_steps:
        return FailureStepProvenance(
            FAILURE_STEP_UNAVAILABLE,
            evidence=("No failed-step metadata was available.",),
        )

    named_steps = [
        str(step.get("name") or "").strip()
        for step in failed_steps
        if str(step.get("name") or "").strip()
    ]
    if len(failed_steps) == 1 and len(named_steps) == 1:
        step_name = named_steps[0]
        return FailureStepProvenance(
            FAILURE_STEP_CONFIRMED,
            step_name=step_name,
            evidence=(f"failed step: {step_name}",),
        )

    labels = tuple(
        str(step.get("name") or "unnamed step").strip() or "unnamed step"
        for step in failed_steps[:5]
    )
    return FailureStepProvenance(
        FAILURE_STEP_AMBIGUOUS,
        evidence=(
            f"Multiple failed steps were present: {', '.join(labels)}",
        ),
    )


def assess_execution_provenance(
    job: dict,
    log_text: str,
    classification: Classification,
) -> ExecutionProvenance:
    """Bind transient failure evidence to the GitHub step that actually failed."""
    if classification.category not in TRANSIENT_CATEGORIES or classification.confidence != "high":
        return ExecutionProvenance(PROVENANCE_NOT_APPLICABLE)

    failed_steps = [
        step for step in (job.get("steps") or [])
        if str(step.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]
    if not failed_steps:
        return ExecutionProvenance(
            PROVENANCE_UNAVAILABLE,
            evidence=("No failed-step metadata was available.",),
        )

    evidence_lines = set(classification.evidence)
    timestamped_evidence: list[tuple[datetime, str]] = []
    exit_lines: list[tuple[datetime, str]] = []
    for raw_line in log_text.splitlines():
        timestamp = _raw_line_timestamp(raw_line)
        if timestamp is None:
            continue
        cleaned = _useful_line(raw_line)
        if cleaned in evidence_lines:
            timestamped_evidence.append((timestamp, cleaned))
        if re.match(r"^process completed with exit code\b", cleaned, re.IGNORECASE):
            exit_lines.append((timestamp, cleaned))

    if not timestamped_evidence:
        return ExecutionProvenance(
            PROVENANCE_UNAVAILABLE,
            evidence=("Transient evidence had no GitHub runner timestamp.",),
        )

    usable_windows = 0
    for step in failed_steps:
        start = _parse_time(step.get("started_at"))
        end = _parse_time(step.get("completed_at"))
        if start is None or end is None or end < start:
            continue
        usable_windows += 1
        window_start = start - timedelta(seconds=2)
        window_end = end + timedelta(seconds=2)
        matched = [
            line for timestamp, line in timestamped_evidence
            if window_start <= timestamp <= window_end
        ]
        if not matched:
            continue

        command = _step_command_in_window(log_text, window_start, window_end)
        proof: list[str] = [f"failed step: {step.get('name') or 'unnamed step'}"]
        if command:
            proof.append(f"command: {command}")
        for line in matched[:2]:
            proof.append(f"signal: {line}")
        matching_exits = [
            line for timestamp, line in exit_lines
            if window_start <= timestamp <= window_end
        ]
        if matching_exits:
            proof.append(f"exit: {matching_exits[-1]}")
        return ExecutionProvenance(
            PROVENANCE_CONFIRMED,
            step_name=str(step.get("name") or ""),
            command=command,
            evidence=tuple(proof[:5]),
        )

    if usable_windows == 0:
        return ExecutionProvenance(
            PROVENANCE_UNAVAILABLE,
            evidence=("Failed-step timing metadata was unavailable.",),
        )
    return ExecutionProvenance(
        PROVENANCE_MISMATCH,
        evidence=("Transient evidence was timestamped outside every failed-step window.",),
    )


def _check_run_id_from_job(job: dict) -> int | None:
    raw_url = str(job.get("check_run_url") or "").strip()
    if not raw_url:
        return None
    try:
        path = urlparse(raw_url).path
    except ValueError:
        return None
    match = re.search(r"/repos/[^/]+/[^/]+/check-runs/(?P<id>\d+)$", path)
    if not match:
        return None
    try:
        return int(match.group("id"))
    except ValueError:
        return None


def assess_authenticated_runner_annotations(
    job: dict,
    check_run: dict,
    annotations: Iterable[dict],
) -> JobAssessment | None:
    """Build retry evidence from a GitHub Actions check annotation.

    This is deliberately a fallback for missing job logs, not a parallel source
    that can override ordinary step-bound log evidence. Authorization requires
    an exact binding between the workflow job and the GitHub Actions check run:
    check-run id, job name, head SHA, conclusion, and app identity.
    """
    job_id = int(job.get("id") or 0)
    check_run_id = _check_run_id_from_job(job)
    if job_id <= 0 or check_run_id is None:
        return None

    try:
        observed_check_id = int(check_run.get("id") or 0)
    except (TypeError, ValueError):
        return None
    if observed_check_id != check_run_id:
        return None

    job_name = str(job.get("name") or "")
    if not job_name or str(check_run.get("name") or "") != job_name:
        return None

    job_head_sha = str(job.get("head_sha") or "").strip()
    check_head_sha = str(check_run.get("head_sha") or "").strip()
    if not job_head_sha or not check_head_sha or check_head_sha != job_head_sha:
        return None

    job_conclusion = str(job.get("conclusion") or "").lower()
    check_conclusion = str(check_run.get("conclusion") or "").lower()
    if (
        job_conclusion not in FAILURE_CONCLUSIONS
        or check_conclusion != job_conclusion
        or str(check_run.get("status") or "").lower() != "completed"
    ):
        return None

    app = check_run.get("app")
    if not isinstance(app, dict) or str(app.get("slug") or "").lower() != "github-actions":
        return None

    messages: list[str] = []
    fields_redacted: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        if str(annotation.get("annotation_level") or "").lower() != "failure":
            continue
        raw_message = str(annotation.get("message") or "").strip()
        if not _RUNNER_LOSS_CHECK_ANNOTATION_RE.search(raw_message):
            continue
        redacted_message, matched_fields = redact_with_provenance(raw_message)
        fields_redacted.update(matched_fields)
        cleaned = _useful_line(redacted_message)
        if cleaned and cleaned not in messages:
            messages.append(cleaned)

    if not messages:
        return None

    classification = classify_log("\n".join(messages))
    if (
        classification.category != "RUNNER_INFRA"
        or classification.confidence != "high"
    ):
        return None

    failure_step = assess_failure_step_provenance(job)
    side_effect_risk, side_effect_evidence = detect_side_effect_risk(job)
    proof = (
        "source: authenticated GitHub Checks annotation",
        f"check_run_id: {check_run_id}",
        "check app: github-actions",
        f"head_sha matched: {job_head_sha}",
        f"signal: {messages[0]}",
    )
    return JobAssessment(
        job_id=job_id,
        name=job_name,
        category=classification.category,
        confidence=classification.confidence,
        evidence=classification.evidence,
        provenance_status=PROVENANCE_CONFIRMED,
        provenance_step="",
        provenance_command="",
        provenance_evidence=proof,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        failure_step_evidence=failure_step.evidence,
        side_effect_risk=side_effect_risk,
        side_effect_evidence=side_effect_evidence,
        duration_minutes=job_duration_minutes(job),
        masking_fields_redacted=tuple(
            sorted(
                fields_redacted
                | set(classification.fields_redacted)
                | set(_metadata_redacted_fields(job))
            )
        ),
    )


def assess_job(job: dict, log_text: str) -> JobAssessment:
    classification = classify_log(log_text)
    provenance = assess_execution_provenance(job, log_text, classification)
    failure_step = assess_failure_step_provenance(job)
    side_effect_risk, side_effect_evidence = detect_side_effect_risk(job)
    return JobAssessment(
        job_id=int(job.get("id") or 0),
        name=str(job.get("name") or f"job-{job.get('id', 'unknown')}"),
        category=classification.category,
        confidence=classification.confidence,
        evidence=classification.evidence,
        provenance_status=provenance.status,
        provenance_step=provenance.step_name,
        provenance_command=provenance.command,
        provenance_evidence=provenance.evidence,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        failure_step_evidence=failure_step.evidence,
        side_effect_risk=side_effect_risk,
        side_effect_evidence=side_effect_evidence,
        duration_minutes=job_duration_minutes(job),
        masking_fields_redacted=tuple(
            sorted(
                set(classification.fields_redacted)
                | set(_metadata_redacted_fields(job))
            )
        ),
    )


def _normalized_job_stem(name: str) -> str:
    """Normalize an explicit primary/retry job identity conservatively."""
    def normalize_component(value: str) -> str:
        value = value.lower()
        value = re.sub(r"\bre-?try\b", "", value)
        value = re.sub(r"[_\-]+", " ", value)
        value = re.sub(r"[()\[\]]+", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    parts = [normalize_component(part) for part in name.split("/")]
    parts = [part for part in parts if part]
    return " / ".join(parts)


def _job_identity_matches(primary_name: str, retry_name: str) -> bool:
    primary_parts = [part.strip() for part in _normalized_job_stem(primary_name).split(" / ")]
    retry_parts = [part.strip() for part in _normalized_job_stem(retry_name).split(" / ")]
    if not primary_parts or not retry_parts:
        return False
    if len(primary_parts) > 1 and len(retry_parts) > 1:
        return primary_parts[-1] == retry_parts[-1]
    return primary_parts == retry_parts

def detect_recovered_failures(failed_jobs: Iterable[dict], jobs: Iterable[dict]) -> dict[int, str]:
    """Return failed job ids that have an explicit successful retry counterpart.

    Metadata-only recovery is accepted only when the successful job explicitly
    identifies itself as a retry and its normalized display name matches the
    failed primary. This prevents 'some later job succeeded' from becoming
    recovery evidence.
    """
    successful = [
        job for job in jobs
        if str(job.get("conclusion") or "").lower() == "success"
        and re.search(r"\bretry\b|re-?try", str(job.get("name") or ""), re.IGNORECASE)
    ]
    recovered: dict[int, str] = {}
    for failed in failed_jobs:
        failed_name = str(failed.get("name") or "")
        failed_stem = _normalized_job_stem(failed_name)
        if not failed_stem:
            continue
        for retry in successful:
            retry_name = str(retry.get("name") or "")
            if _job_identity_matches(failed_name, retry_name):
                recovered[int(failed.get("id") or 0)] = retry_name
                break
    return recovered


def detect_cross_attempt_recovery(failed_jobs: Iterable[dict], later_jobs: Iterable[dict]) -> dict[int, str]:
    """Match failed jobs to successful jobs with the same identity in a later attempt."""
    successful = [
        job for job in later_jobs
        if str(job.get("conclusion") or "").lower() == "success"
    ]
    recovered: dict[int, str] = {}
    for failed in failed_jobs:
        failed_name = str(failed.get("name") or "")
        if not failed_name:
            continue
        for later in successful:
            later_name = str(later.get("name") or "")
            if _normalized_job_stem(failed_name) == _normalized_job_stem(later_name):
                recovered[int(failed.get("id") or 0)] = later_name
                break
    return recovered



def detect_cross_attempt_recurrence(failed_jobs: Iterable[dict], later_jobs: Iterable[dict]) -> dict[int, str]:
    """Match a failed job identity that fails again in the next attempt."""
    failed_later = [job for job in later_jobs if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS]
    recurrent: dict[int, str] = {}
    for failed in failed_jobs:
        failed_name = str(failed.get("name") or "")
        for later in failed_later:
            later_name = str(later.get("name") or "")
            if failed_name and _normalized_job_stem(failed_name) == _normalized_job_stem(later_name):
                recurrent[int(failed.get("id") or 0)] = later_name
                break
    return recurrent


def historical_reliability_record(
    current_failed_jobs: Iterable[dict],
    prior_incidents: Iterable[dict],
    cutoff: str,
) -> dict:
    """Summarize only machine-verified recoveries observed before the current failure.

    History is supporting evidence. It never authorizes a rerun by itself.
    Each incident must carry observed_at, failed_jobs, and later_jobs metadata.
    """
    identities = {
        _normalized_job_stem(str(job.get("name") or ""))
        for job in current_failed_jobs
        if str(job.get("name") or "")
    }
    verified: list[dict] = []
    for incident in prior_incidents:
        observed_at = str(incident.get("observed_at") or "")
        if not observed_at or observed_at >= cutoff:
            continue
        failed = list(incident.get("failed_jobs") or [])
        later = list(incident.get("later_jobs") or [])
        recovered = detect_cross_attempt_recovery(failed, later)
        for job in failed:
            job_id = int(job.get("id") or 0)
            identity = _normalized_job_stem(str(job.get("name") or ""))
            if identity in identities and job_id in recovered:
                verified.append({
                    "run_id": int(incident.get("run_id") or 0),
                    "identity": identity,
                    "observed_at": observed_at,
                    "recovered_as": recovered[job_id],
                })
    unique_incidents = {
        (item["run_id"], item["observed_at"])
        for item in verified
    }
    by_identity: dict[str, int] = {}
    for item in verified:
        by_identity[item["identity"]] = by_identity.get(item["identity"], 0) + 1
    latest = max((item["observed_at"] for item in verified), default=None)
    return {
        "status": "SUPPORTING_EVIDENCE" if verified else "INSUFFICIENT_HISTORY",
        "verified_prior_recoveries": len(verified),
        "verified_prior_incidents": len(unique_incidents),
        "recoveries_by_identity": by_identity,
        "latest_verified_recovery_at": latest,
        "cutoff": cutoff,
        "authorization": "NOT_AUTHORIZING",
        "recoveries": verified,
    }


def collect_historical_reliability(
    api: "GitHubAPI",
    repo: str,
    current_run: dict,
    current_failed_jobs: Iterable[dict],
    *,
    max_pages: int = 4,
    per_page: int = 100,
    max_candidate_runs: int = 12,
) -> dict:
    """Collect pre-failure recovery history with a bounded API evidence budget.

    Stage 1 is cheap workflow-list discovery. Stage 2 spends attempt/job calls
    only on list records that already report multiple attempts. Rate limiting is
    evidence unavailability, never a reason to authorize execution.
    """
    cutoff = str(current_run.get("created_at") or "")
    workflow_id = int(current_run.get("workflow_id") or 0)
    if not cutoff or not workflow_id:
        return historical_reliability_record(current_failed_jobs, [], cutoff)

    candidates: list[dict] = []
    pages_examined = 0
    rate_limited = False
    try:
        for page in range(1, max_pages + 1):
            batch = api.get_workflow_runs(repo, workflow_id, per_page=per_page, page=page)
            pages_examined += 1
            if not batch:
                break
            for run in batch:
                if (
                    str(run.get("created_at") or "") < cutoff
                    and int(run.get("id") or 0) != int(current_run.get("id") or 0)
                    and int(run.get("run_attempt") or 1) > 1
                ):
                    candidates.append(run)
                    if len(candidates) >= max_candidate_runs:
                        break
            if len(candidates) >= max_candidate_runs or len(batch) < per_page:
                break
    except RuntimeError as exc:
        if "rate limit exceeded" in str(exc).lower():
            rate_limited = True
        else:
            raise

    incidents: list[dict] = []
    inspected = 0
    for prior in candidates[:max_candidate_runs]:
        prior_id = int(prior.get("id") or 0)
        final_attempt = int(prior.get("run_attempt") or 1)
        try:
            first_jobs = api.get_jobs_attempt(repo, prior_id, 1)
            later_jobs = api.get_jobs_attempt(repo, prior_id, final_attempt)
        except RuntimeError as exc:
            if "rate limit exceeded" in str(exc).lower():
                rate_limited = True
                break
            raise
        inspected += 1
        failed = [
            job for job in first_jobs
            if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
        ]
        if failed:
            incidents.append({
                "run_id": prior_id,
                "observed_at": str(prior.get("created_at") or ""),
                "failed_jobs": failed,
                "later_jobs": later_jobs,
            })

    record = historical_reliability_record(current_failed_jobs, incidents, cutoff)
    if rate_limited and not record["verified_prior_recoveries"]:
        record["status"] = "EVIDENCE_RATE_LIMITED"
    record["workflow_id"] = workflow_id
    record["pages_examined"] = pages_examined
    record["candidate_runs"] = len(candidates)
    record["candidate_runs_inspected"] = inspected
    record["evidence_budget_exhausted"] = (
        rate_limited or pages_examined >= max_pages or len(candidates) >= max_candidate_runs
    )
    return record


def _evidence_artifact_path(repo: str, run_id: int, run_attempt: int) -> Path:
    root = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir())
    directory = root / "ci-retry-gate-evidence"
    safe_repo = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repository"
    return directory / f"{safe_repo}-run-{run_id}-attempt-{run_attempt}.evidence.json"


def _run_evidence_gate_process(
    evidence_path: Path,
    evidence_sha256: str,
    max_attempts: int,
) -> dict:
    """Invoke the authorization gate in a separate Python process."""
    gate_cli = Path(__file__).with_name("evidence_gate_cli.py")
    completed = subprocess.run(
        [
            sys.executable,
            str(gate_cli),
            "--evidence",
            str(evidence_path),
            "--expected-sha256",
            evidence_sha256,
            "--max-attempts",
            str(max_attempts),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(
            "Evidence gate process failed closed"
            + (f": {stderr}" if stderr else "")
        )
    try:
        decision = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Evidence gate returned invalid JSON") from exc
    if not isinstance(decision, dict):
        raise RuntimeError("Evidence gate returned a non-object decision")
    if decision.get("decision") not in {"ALLOW", "BLOCK"}:
        raise RuntimeError("Evidence gate returned an invalid authorization decision")
    reasons = decision.get("reasons")
    if not isinstance(reasons, list) or not reasons:
        raise RuntimeError("Evidence gate returned no decision reason")
    return decision


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow GitHub log redirects without forwarding the bearer token cross-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urlparse(req.full_url).netloc
        new_host = urlparse(newurl).netloc
        if old_host and new_host and old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


class GitHubAPI:
    def __init__(self, token: str, api_url: str = "https://api.github.com"):
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.opener = urllib.request.build_opener(_SafeRedirectHandler())

    def request(self, method: str, path: str, payload: dict | None = None, accept: str = "application/vnd.github+json"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        attempts = 3 if method.upper() == "GET" else 1
        last_transport_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            headers = {
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ci-retry-gate-action",
                "Content-Type": "application/json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(
                f"{self.api_url}{path}",
                data=data,
                method=method,
                headers=headers,
            )
            try:
                with self.opener.open(req, timeout=30) as response:
                    body = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type:
                        return json.loads(body.decode("utf-8"))
                    return body.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"GitHub API {method} {path} failed with HTTP {exc.code}: {body[:500]}"
                ) from exc
            except (
                http.client.IncompleteRead,
                http.client.RemoteDisconnected,
                ConnectionResetError,
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_transport_error = exc
                if attempt >= attempts:
                    break
                time.sleep(0.25 * attempt)

        raise RuntimeError(
            f"GitHub API {method} {path} failed after {attempts} transport attempts: "
            f"{type(last_transport_error).__name__}: {last_transport_error}"
        ) from last_transport_error

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> bytes:
        attempts = 3 if method.upper() == "GET" else 1
        last_transport_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            headers = {
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ci-retry-gate-action",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            req = urllib.request.Request(
                f"{self.api_url}{path}",
                method=method,
                headers=headers,
            )
            try:
                with self.opener.open(req, timeout=30) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"GitHub API {method} {path} failed with HTTP {exc.code}: {body[:500]}"
                ) from exc
            except (
                http.client.IncompleteRead,
                http.client.RemoteDisconnected,
                ConnectionResetError,
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_transport_error = exc
                if attempt >= attempts:
                    break
                time.sleep(0.25 * attempt)

        raise RuntimeError(
            f"GitHub API {method} {path} failed after {attempts} transport attempts: "
            f"{type(last_transport_error).__name__}: {last_transport_error}"
        ) from last_transport_error

    def get_repository(self, repo: str) -> dict:
        return self.request("GET", f"/repos/{repo}")

    def get_run(self, repo: str, run_id: int) -> dict:
        return self.request("GET", f"/repos/{repo}/actions/runs/{run_id}")

    def get_run_attempt(self, repo: str, run_id: int, run_attempt: int) -> dict:
        return self.request("GET", f"/repos/{repo}/actions/runs/{run_id}/attempts/{run_attempt}")

    def get_jobs(self, repo: str, run_id: int) -> list[dict]:
        data = self.request("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
        return list(data.get("jobs") or [])

    def get_workflow_runs(self, repo: str, workflow_id: int, per_page: int = 100, page: int = 1) -> list[dict]:
        data = self.request(
            "GET",
            f"/repos/{repo}/actions/workflows/{workflow_id}/runs?per_page={per_page}&page={page}",
        )
        return list(data.get("workflow_runs") or [])

    def get_jobs_attempt(self, repo: str, run_id: int, run_attempt: int) -> list[dict]:
        data = self.request(
            "GET",
            f"/repos/{repo}/actions/runs/{run_id}/attempts/{run_attempt}/jobs?per_page=100",
        )
        return list(data.get("jobs") or [])

    def get_check_run(self, repo: str, check_run_id: int) -> dict:
        data = self.request("GET", f"/repos/{repo}/check-runs/{check_run_id}")
        if not isinstance(data, dict):
            raise RuntimeError("GitHub Checks API returned a non-object check run")
        return data

    def get_check_run_annotations(
        self,
        repo: str,
        check_run_id: int,
        *,
        max_pages: int = 5,
    ) -> list[dict]:
        annotations: list[dict] = []
        for page in range(1, max_pages + 1):
            data = self.request(
                "GET",
                f"/repos/{repo}/check-runs/{check_run_id}/annotations"
                f"?per_page=100&page={page}",
            )
            if not isinstance(data, list):
                raise RuntimeError(
                    "GitHub Checks API returned a non-array annotation response"
                )
            annotations.extend(item for item in data if isinstance(item, dict))
            if len(data) < 100:
                return annotations
        raise RuntimeError(
            "GitHub Checks annotation pagination budget exhausted before completion"
        )

    def get_job_logs(self, repo: str, job_id: int) -> str:
        # Job logs are a text/archive response (and may redirect to GitHub's blob
        # storage), not a JSON resource. Reading them through request() can
        # stringify/transform the response path and hide the exact runner
        # evidence the classifier needs. Preserve the response bytes verbatim
        # and decode only after the safe redirect handler has removed auth on
        # cross-host redirects.
        raw = self.request_bytes(
            "GET",
            f"/repos/{repo}/actions/jobs/{job_id}/logs",
            accept="application/vnd.github+json",
        )
        text = raw.decode("utf-8", errors="replace")
        if _bool_env("CI_RETRY_GATE_LOG_DIAGNOSTICS", False):
            lowered = text.lower()
            print(
                "::notice::job-log diagnostics "
                f"job_id={job_id} bytes={len(raw)} chars={len(text)} "
                f"has_shutdown_signal={'the runner has received a shutdown signal' in lowered} "
                f"has_operation_canceled={'the operation was canceled' in lowered} "
                f"starts_with={text[:80].replace(chr(10), ' ').replace(chr(13), ' ')!r}"
            )
        return text

    def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs", payload={})

    def post_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        self.request("POST", f"/repos/{repo}/issues/{pr_number}/comments", payload={"body": body})


def _event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def render_report(repo: str, run_id: int, run_attempt: int, assessments: list[JobAssessment], safe: bool, reason: str, rerun_triggered: bool, recovered: dict[int, str] | None = None, historical: dict | None = None, recurrent: dict[int, str] | None = None, decision_experience: dict | None = None) -> str:
    wasted = round(sum(item.duration_minutes for item in assessments), 2)
    lines = [
        "<!-- ci-retry-gate-report -->",
        "## CI Retry Gate",
        "",
        f"Repository: `{repo}` · Run: `{run_id}` · Attempt: `{run_attempt}`",
        "",
        f"**Decision:** {'SAFE TO RERUN' if safe else 'DO NOT AUTO-RERUN'}",
        "",
        f"{reason}",
        "",
    ]
    if decision_experience:
        lines.extend(render_decision_card(decision_experience).rstrip().splitlines())
        lines.append("")
    recovered = recovered or {}
    if recovered:
        lines.extend([
            "### Recovery evidence",
            "",
            "The rerun decision below is based on explicit recovery metadata; failure-cause logs are a separate evidence channel.",
            "",
        ])
        for item in assessments:
            retry_name = recovered.get(item.job_id)
            if retry_name:
                lines.append(f"- `{item.name}` failed → explicit retry `{retry_name}` succeeded.")
        lines.append("")
    recurrent = recurrent or {}
    if recurrent:
        lines.extend(["### Recurrence evidence", "", "The next attempt repeated the same failed job identity; later eventual success does not erase this failed rerun.", ""])
        for item in assessments:
            later_name = recurrent.get(item.job_id)
            if later_name:
                lines.append(f"- `{item.name}` failed → next attempt `{later_name}` failed again.")
        lines.append("")
    historical = historical or {}
    if historical:
        lines.extend([
            "### Historical reliability",
            "",
            f"- Status: `{historical.get('status', 'INSUFFICIENT_HISTORY')}`",
            f"- Verified prior recoveries (job-level): **{historical.get('verified_prior_recoveries', 0)}**",
            f"- Independent prior incidents: **{historical.get('verified_prior_incidents', 0)}**",
            f"- Recoveries by job identity: `{json.dumps(historical.get('recoveries_by_identity', {}), sort_keys=True)}`",
            f"- Latest verified recovery: `{historical.get('latest_verified_recovery_at') or 'none'}`",
            f"- Evidence cutoff: `{historical.get('cutoff') or 'unknown'}`",
            f"- Authorization: `{historical.get('authorization', 'NOT_AUTHORIZING')}`",
            "",
        ])
    lines.extend([
        f"Failed-job runtime observed: **{wasted:.2f} min**",
        "",
        "| Job | Classification | Confidence | Retry provenance | Outcome step | Side-effect risk | Runtime |",
        "|---|---|---|---|---|---|---:|",
    ])
    for item in assessments:
        lines.append(
            f"| {item.name.replace('|', '/')} | `{item.category}` | {item.confidence} | "
            f"`{item.provenance_status}` | `{item.failure_step_status}` | "
            f"{'YES' if item.side_effect_risk else 'no'} | {item.duration_minutes:.2f} min |"
        )
    for item in assessments:
        lines.extend(["", f"### {item.name}"])
        if item.evidence:
            lines.append("Evidence:")
            for evidence in item.evidence:
                lines.append(f"- `{evidence.replace('`', "'")}`")
        else:
            lines.append("- No strong signature found in the available log.")
        if item.provenance_evidence:
            lines.append("Retry-authority execution provenance:")
            for evidence in item.provenance_evidence:
                lines.append(f"- `{evidence.replace('`', "\'")}`")
        if item.failure_step_evidence:
            lines.append("Outcome failure-step provenance:")
            for evidence in item.failure_step_evidence:
                lines.append(f"- `{evidence.replace(chr(96), chr(39))}`")
        if item.side_effect_evidence:
            lines.append("Side-effect signals:")
            for evidence in item.side_effect_evidence:
                lines.append(f"- `{evidence.replace('`', "'")}`")
    lines.extend(["", f"Automatic rerun triggered: **{'yes' if rerun_triggered else 'no'}**"])
    return "\n".join(lines) + "\n"


def assess_failed_jobs(api: "GitHubAPI", repo: str, failed_jobs: Iterable[dict]) -> list[JobAssessment]:
    """Assess failed jobs and fail closed when log evidence cannot be acquired."""
    assessments: list[JobAssessment] = []
    for job in failed_jobs:
        job_id = int(job.get("id") or 0)
        try:
            logs = api.get_job_logs(repo, job_id)
        except RuntimeError as exc:
            # A runner can die before its log blob is finalized. In that narrow
            # case GitHub may still retain a failure annotation on the Actions
            # check run. Use it only through an authenticated token and only
            # when the check run is exactly bound to this job/head.
            error_text = redact(str(exc))
            annotation_note = "Authenticated check annotation fallback was not available."
            check_run_id = _check_run_id_from_job(job)
            api_token = str(getattr(api, "token", "") or "")
            if api_token and check_run_id is not None:
                try:
                    check_run = api.get_check_run(repo, check_run_id)
                    annotations = api.get_check_run_annotations(repo, check_run_id)
                except RuntimeError as annotation_exc:
                    annotation_note = (
                        "Authenticated check annotation acquisition failed: "
                        f"{redact(str(annotation_exc))}"
                    )
                else:
                    annotation_assessment = assess_authenticated_runner_annotations(
                        job,
                        check_run,
                        annotations,
                    )
                    if annotation_assessment is not None:
                        if _bool_env("CI_RETRY_GATE_LOG_DIAGNOSTICS", False):
                            print(
                                "::notice::using authenticated check annotation fallback "
                                f"job_id={job_id} check_run_id={check_run_id}"
                            )
                        assessments.append(annotation_assessment)
                        continue
                    annotation_note = (
                        "Authenticated check annotations contained no eligible "
                        "job-bound runner-loss signal."
                    )
            elif not api_token:
                annotation_note = (
                    "Authenticated check annotation fallback requires a GitHub token."
                )
            elif check_run_id is None:
                annotation_note = (
                    "Workflow job metadata did not contain a valid check_run_url."
                )

            # Evidence acquisition failure is not an ordinary UNKNOWN
            # classification. Keep it explicit so downstream authorization can
            # distinguish "log inspected, no signature found" from "the log
            # could not be inspected at all".
            if _bool_env("CI_RETRY_GATE_LOG_DIAGNOSTICS", False):
                print(
                    "::warning::job-log acquisition failed "
                    f"job_id={job_id} error={error_text}"
                )
            failure_step = assess_failure_step_provenance(job)
            side_effect_risk, side_effect_evidence = detect_side_effect_risk(job)
            assessments.append(
                JobAssessment(
                    job_id=job_id,
                    name=str(job.get("name") or f"job-{job_id}"),
                    category="EVIDENCE_UNAVAILABLE",
                    confidence="none",
                    evidence=(
                        f"Job log acquisition failed: {error_text}",
                        annotation_note,
                    ),
                    provenance_status=PROVENANCE_UNAVAILABLE,
                    provenance_step="",
                    provenance_command="",
                    provenance_evidence=("Execution evidence was unavailable.",),
                    failure_step_status=failure_step.status,
                    failure_step=failure_step.step_name,
                    failure_step_evidence=failure_step.evidence,
                    side_effect_risk=side_effect_risk,
                    side_effect_evidence=side_effect_evidence,
                    duration_minutes=job_duration_minutes(job),
                )
            )
            continue
        assessments.append(assess_job(job, logs))

    return assessments


def _state_binding_token(value: object) -> str:
    """Canonicalize one domain value into a non-empty opaque EASL token."""
    return "json:" + json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _failed_job_binding_value(jobs: Iterable[dict]) -> list[list[object]]:
    return sorted(
        [
            [
                int(job.get("id") or 0),
                str(job.get("conclusion") or "").lower(),
            ]
            for job in jobs
            if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
        ],
        key=lambda item: (int(item[0]), str(item[1])),
    )


def _changed_binding_reason(
    invalidation_ids: Iterable[str],
    details: dict[str, str],
) -> str | None:
    changed = [details[binding_id] for binding_id in invalidation_ids if binding_id in details]
    if not changed:
        return None
    return "RERUN_SCOPE_CHANGED: " + "; ".join(changed) + "."


def revalidate_rerun_subject_binding(
    api: "GitHubAPI",
    repo: str,
    run_id: int,
    evidence_decision: dict,
    expected_failed_jobs: Iterable[dict],
) -> tuple[bool, str]:
    """Re-read the target run and evaluate its subject state with EASL semantics."""
    scope = evidence_decision.get("scope")
    if not isinstance(scope, dict):
        return False, "RERUN_SCOPE_INVALID: evidence decision has no valid scope."

    expected_repository = str(scope.get("repository") or "")
    try:
        expected_run_id = int(scope.get("run_id"))
        expected_attempt = int(scope.get("run_attempt"))
    except (TypeError, ValueError):
        return False, "RERUN_SCOPE_INVALID: run_id/run_attempt binding is missing or invalid."

    static_bindings = (
        StateBinding(
            id="repository",
            expected=_state_binding_token(expected_repository),
            observed=_state_binding_token(repo),
        ),
        StateBinding(
            id="run-id",
            expected=_state_binding_token(expected_run_id),
            observed=_state_binding_token(run_id),
        ),
    )
    static_details = {
        "repository": f"repository {expected_repository!r}->{repo!r}",
        "run-id": f"run_id {expected_run_id}->{run_id}",
    }
    try:
        static_invalidations = evaluate_required_state_bindings(
            static_bindings,
            ("repository", "run-id"),
        )
    except StateBindingError as exc:
        return False, f"RERUN_SCOPE_INVALID: {exc}."

    static_reason = _changed_binding_reason(
        (item.state_binding_id for item in static_invalidations),
        static_details,
    )
    if static_reason is not None:
        return False, static_reason

    current_run = api.get_run(repo, run_id)
    current_attempt = int(current_run.get("run_attempt") or 0)
    current_head_sha = str(current_run.get("head_sha") or "")
    current_workflow_id = current_run.get("workflow_id")

    expected_head_sha = str(scope.get("head_sha") or "")
    expected_workflow_id = scope.get("workflow_id")

    current_jobs = api.get_jobs(repo, run_id)
    expected_failed = _failed_job_binding_value(expected_failed_jobs)
    current_failed = _failed_job_binding_value(current_jobs)

    dynamic_bindings = (
        StateBinding(
            id="run-attempt",
            expected=_state_binding_token(expected_attempt),
            observed=_state_binding_token(current_attempt),
        ),
        StateBinding(
            id="head-sha",
            expected=_state_binding_token(expected_head_sha),
            observed=_state_binding_token(current_head_sha),
        ),
        StateBinding(
            id="workflow-id",
            expected=_state_binding_token(expected_workflow_id),
            observed=_state_binding_token(current_workflow_id),
        ),
        StateBinding(
            id="failed-job-set",
            expected=_state_binding_token(expected_failed),
            observed=_state_binding_token(current_failed),
        ),
    )
    dynamic_details = {
        "run-attempt": f"run_attempt {expected_attempt}->{current_attempt}",
        "head-sha": f"head_sha {expected_head_sha!r}->{current_head_sha!r}",
        "workflow-id": (
            f"workflow_id {expected_workflow_id!r}->{current_workflow_id!r}"
        ),
        "failed-job-set": (
            f"failed_job_set {expected_failed!r}->{current_failed!r}"
        ),
    }
    try:
        dynamic_invalidations = evaluate_required_state_bindings(
            dynamic_bindings,
            ("run-attempt", "head-sha", "workflow-id", "failed-job-set"),
        )
    except StateBindingError as exc:
        return False, f"RERUN_SCOPE_INVALID: {exc}."

    dynamic_reason = _changed_binding_reason(
        (item.state_binding_id for item in dynamic_invalidations),
        dynamic_details,
    )
    if dynamic_reason is not None:
        return False, dynamic_reason

    return True, (
        "RERUN_SCOPE_CONFIRMED: repository, run attempt, head SHA, workflow, "
        "and failed-job set still match the evidence decision."
    )


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    event = _event_payload()
    workflow_run = event.get("workflow_run") or {}
    run_id_raw = os.environ.get("INPUT_RUN_ID") or workflow_run.get("id") or os.environ.get("GITHUB_RUN_ID")

    public_read_only = _bool_env("INPUT_PUBLIC_READ_ONLY", False)
    if not token and not public_read_only:
        print("::error::github-token is required unless public-read-only mode is enabled")
        return 2
    if not repo:
        print("::error::repository could not be determined")
        return 2
    try:
        run_id = int(run_id_raw)
    except (TypeError, ValueError):
        print("::error::run-id could not be determined")
        return 2

    max_attempts = int(os.environ.get("INPUT_MAX_ATTEMPTS", "2"))
    auto_rerun = _bool_env("INPUT_AUTO_RERUN", False)
    comment_on_pr = _bool_env("INPUT_COMMENT_ON_PR", False)
    if public_read_only and (auto_rerun or comment_on_pr):
        print("::error::public-read-only mode cannot rerun jobs or post into the target repository")
        return 2
    run_attempt_raw = (os.environ.get("INPUT_RUN_ATTEMPT") or "").strip()
    selected_run_attempt: int | None = None
    if run_attempt_raw:
        try:
            selected_run_attempt = int(run_attempt_raw)
        except ValueError:
            print("::error::run-attempt must be a positive integer")
            return 2
        if selected_run_attempt < 1:
            print("::error::run-attempt must be a positive integer")
            return 2
        if auto_rerun:
            print("::error::run-attempt is read-only and cannot be combined with auto-rerun")
            return 2

    # Public proof deliberately avoids forwarding the workflow's installation token to
    # another repository. GitHub's public Actions read endpoints support unauthenticated
    # access, so the proof surface needs no target-repository installation or permission.
    api = GitHubAPI("" if public_read_only else str(token), os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    if public_read_only:
        repository = api.get_repository(repo)
        if bool(repository.get("private", True)):
            print("::error::public-read-only mode only supports public repositories")
            return 2

    if selected_run_attempt is None:
        run = api.get_run(repo, run_id)
        run_attempt = int(run.get("run_attempt") or 1)
        jobs = api.get_jobs(repo, run_id)
    else:
        run = api.get_run_attempt(repo, run_id, selected_run_attempt)
        run_attempt = selected_run_attempt
        jobs = api.get_jobs_attempt(repo, run_id, selected_run_attempt)
    failed_jobs = [job for job in jobs if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS]

    assessments = assess_failed_jobs(api, repo, failed_jobs)
    evidence_bundle = produce_ci_evidence_bundle(
        repo=repo,
        run=run,
        run_id=run_id,
        run_attempt=run_attempt,
        assessments=assessments,
    )
    evidence_path = _evidence_artifact_path(repo, run_id, run_attempt)
    evidence_sha256 = write_evidence_artifact(evidence_path, evidence_bundle)
    evidence_decision = _run_evidence_gate_process(
        evidence_path,
        evidence_sha256,
        max_attempts,
    )
    safe = evidence_decision["decision"] == "ALLOW"
    reason = str(evidence_decision["reasons"][0])

    action_request = build_ci_action_request(
        repository=repo,
        run_id=run_id,
        run_attempt=run_attempt,
        head_sha=str(run.get("head_sha") or ""),
        workflow_id=run.get("workflow_id"),
    )
    contract_timestamp = str(action_request["created_at"])
    assumption_state = build_ci_retry_assumption_state(
        action_request=action_request,
        evidence_decision=evidence_decision,
        evidence_sha256=evidence_sha256,
        created_at=contract_timestamp,
    )
    authority_grant = build_ci_authority_grant(
        action_request=action_request,
        created_at=contract_timestamp,
    )
    contract_decision = build_decision_artifact(
        action_request=action_request,
        evidence_decision=evidence_decision,
        evidence_sha256=evidence_sha256,
        assumption_states=[assumption_state],
        authority_grant=authority_grant,
        require_authority=True,
        created_at=contract_timestamp,
    )

    recovered = detect_recovered_failures(failed_jobs, jobs)
    recurrent: dict[int, str] = {}
    recovery_scope = "same attempt"
    if failed_jobs and len(recovered) != len(failed_jobs) and selected_run_attempt is not None:
        latest_run = api.get_run(repo, run_id)
        latest_attempt = int(latest_run.get("run_attempt") or selected_run_attempt)
        if latest_attempt > selected_run_attempt:
            later_jobs = api.get_jobs_attempt(repo, run_id, selected_run_attempt + 1)
            recovered = detect_cross_attempt_recovery(failed_jobs, later_jobs)
            recurrent = detect_cross_attempt_recurrence(failed_jobs, later_jobs)
            recovery_scope = f"attempt {selected_run_attempt + 1}"
    outer_guard_applied = False
    if failed_jobs and len(recovered) == len(failed_jobs):
        outer_guard_applied = True
        pairs = "; ".join(
            f"{str(job.get('name') or job.get('id'))} -> {recovered[int(job.get('id') or 0)]}"
            for job in failed_jobs
        )
        safe = False
        reason = (
            "FAILURE_RECOVERED: every failed job has an explicit successful retry "
            f"counterpart in {recovery_scope} ({pairs}). Another automatic rerun is not justified."
        )
    elif recurrent:
        outer_guard_applied = True
        pairs = "; ".join(
            f"{str(job.get('name') or job.get('id'))} -> {recurrent[int(job.get('id') or 0)]}"
            for job in failed_jobs if int(job.get("id") or 0) in recurrent
        )
        safe = False
        reason = (
            "NEXT_ATTEMPT_RECURRENCE: the same failed job identity failed again in "
            f"{recovery_scope} ({pairs}). A successful later attempt must not erase this recurrence."
        )
    rerun_triggered = False
    execution_time: str | None = None
    if safe and auto_rerun:
        try:
            binding_valid, binding_reason = revalidate_rerun_subject_binding(
                api,
                repo,
                run_id,
                evidence_decision,
                failed_jobs,
            )
        except RuntimeError as exc:
            binding_valid = False
            binding_reason = (
                "RERUN_SCOPE_UNAVAILABLE: could not re-read current workflow state "
                f"before rerun: {redact(str(exc))}"
            )

        if not binding_valid:
            safe = False
            reason = binding_reason
            outer_guard_applied = True
        else:
            try:
                execution_time = (
                    datetime.now(timezone.utc)
                    .isoformat(timespec="seconds")
                    .replace("+00:00", "Z")
                )
                ensure_decision_allows_request(
                    contract_decision,
                    action_request,
                    now=execution_time,
                    assumption_states=[assumption_state],
                    authority_grant=authority_grant,
                )
            except ContractViolation as exc:
                safe = False
                reason = f"INTEGRATION_CONTRACT_BLOCK: {exc}."
                outer_guard_applied = True
            else:
                api.rerun_failed_jobs(repo, run_id)
                rerun_triggered = True

    historical = collect_historical_reliability(api, repo, run, failed_jobs)

    # Recovery/recurrence checks are conservative outer guards. They may only
    # narrow an ALLOW returned by the isolated gate; they can never create one.
    if outer_guard_applied:
        evidence_decision["decision"] = "BLOCK"
        evidence_decision["reasons"] = [reason]
        if evidence_decision.get("contradictions"):
            evidence_decision["evidence_status"] = "CONTRADICTED"
            evidence_decision["confidence"] = "high"
        else:
            evidence_decision["evidence_status"] = "UNKNOWN"
            evidence_decision["confidence"] = "unknown"
    evidence_decision["rerun_triggered"] = rerun_triggered

    # Rebuild the public contract from the final narrowed decision. If execution
    # occurred, this is identical to the Decision checked at the boundary.
    contract_decision = build_decision_artifact(
        action_request=action_request,
        evidence_decision=evidence_decision,
        evidence_sha256=evidence_sha256,
        assumption_states=[assumption_state],
        authority_grant=authority_grant,
        require_authority=True,
        created_at=contract_timestamp,
    )
    execution_receipt = build_execution_receipt(
        action_request=action_request,
        decision_artifact=contract_decision,
        assumption_states=[assumption_state],
        authority_grant=authority_grant,
        rerun_triggered=rerun_triggered,
        admitted_at=execution_time,
    )

    request_path = evidence_path.with_name(
        evidence_path.name.replace(".evidence.json", ".eba-request.json")
    )
    assumption_path = evidence_path.with_name(
        evidence_path.name.replace(".evidence.json", ".eba-assumption.json")
    )
    authority_path = evidence_path.with_name(
        evidence_path.name.replace(".evidence.json", ".eba-authority.json")
    )
    decision_path = evidence_path.with_name(
        evidence_path.name.replace(".evidence.json", ".eba-decision.json")
    )
    receipt_path = evidence_path.with_name(
        evidence_path.name.replace(".evidence.json", ".eba-receipt.json")
    )
    request_sha256 = write_contract_artifact(request_path, action_request)
    assumption_sha256 = write_contract_artifact(assumption_path, assumption_state)
    authority_sha256 = write_contract_artifact(authority_path, authority_grant)
    decision_sha256 = write_contract_artifact(decision_path, contract_decision)
    receipt_sha256 = write_contract_artifact(receipt_path, execution_receipt)

    decision_experience = build_decision_experience(
        evidence_decision=evidence_decision,
        assessments=assessments,
        rerun_triggered=rerun_triggered,
        run_attempt=run_attempt,
        max_attempts=max_attempts,
    )
    report = render_report(
        repo,
        run_id,
        run_attempt,
        assessments,
        safe,
        reason,
        rerun_triggered,
        recovered,
        historical,
        recurrent,
        decision_experience,
    )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)

    report_file = (os.environ.get("CI_RETRY_GATE_REPORT_FILE") or "").strip()
    if report_file:
        Path(report_file).write_text(report, encoding="utf-8")

    prs = workflow_run.get("pull_requests") or []
    if comment_on_pr and prs:
        pr_number = prs[0].get("number")
        if pr_number:
            try:
                api.post_pr_comment(repo, int(pr_number), report)
            except RuntimeError as exc:
                print(f"::warning::Could not post PR comment: {exc}")

    _write_output("decision", str(evidence_decision["decision"]))
    _write_output("evidence-status", str(evidence_decision["evidence_status"]))
    _write_output("reason", reason)
    _write_output(
        "decision-experience-json",
        json.dumps(decision_experience, separators=(",", ":"), sort_keys=True),
    )
    _write_output("next-action", str(decision_experience["next_action"]))
    _write_output(
        "observed-failed-minutes",
        f"{float(decision_experience['minutes']['observed_failed']):.2f}",
    )
    _write_output(
        "rerun-eligible-jobs",
        str(decision_experience["jobs"]["rerun_eligible"]),
    )
    _write_output(
        "rerun-blocked-jobs",
        str(decision_experience["jobs"]["rerun_blocked"]),
    )
    _write_output(
        "side-effect-blocked-jobs",
        str(decision_experience["jobs"]["side_effect_blocked"]),
    )
    _write_output(
        "evidence-unavailable-jobs",
        str(decision_experience["jobs"]["evidence_unavailable"]),
    )
    _write_output(
        "eligible-failed-minutes",
        f"{float(decision_experience['minutes']['rerun_eligible_failed']):.2f}",
    )
    _write_output(
        "blocked-failed-minutes",
        f"{float(decision_experience['minutes']['rerun_blocked_failed']):.2f}",
    )
    _write_output(
        "failed-jobs-json",
        json.dumps(evidence_decision["failed_jobs"], separators=(",", ":"), sort_keys=True),
    )
    _write_output(
        "evidence-json",
        json.dumps(evidence_decision, separators=(",", ":"), sort_keys=True),
    )
    _write_output("evidence-bundle-path", str(evidence_path))
    _write_output("evidence-bundle-sha256", evidence_sha256)
    _write_output(
        "eba-request-json",
        json.dumps(action_request, separators=(",", ":"), sort_keys=True),
    )
    _write_output("eba-request-sha256", request_sha256)
    _write_output(
        "eba-assumption-json",
        json.dumps(assumption_state, separators=(",", ":"), sort_keys=True),
    )
    _write_output("eba-assumption-sha256", assumption_sha256)
    _write_output(
        "eba-authority-json",
        json.dumps(authority_grant, separators=(",", ":"), sort_keys=True),
    )
    _write_output("eba-authority-sha256", authority_sha256)
    _write_output(
        "eba-decision-json",
        json.dumps(contract_decision, separators=(",", ":"), sort_keys=True),
    )
    _write_output("eba-decision-sha256", decision_sha256)
    _write_output(
        "eba-receipt-json",
        json.dumps(execution_receipt, separators=(",", ":"), sort_keys=True),
    )
    _write_output("eba-receipt-sha256", receipt_sha256)
    _write_output("safe-to-rerun", "true" if safe else "false")
    _write_output("rerun-triggered", "true" if rerun_triggered else "false")
    _write_output("failed-jobs", str(len(assessments)))
    _write_output("wasted-minutes", f"{sum(a.duration_minutes for a in assessments):.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
