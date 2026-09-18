from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ci_retry_gate import CAUSAL, FAILURE_CONCLUSIONS, causal_evidence_role
from transient_mechanism_gate import detect_transient_mechanisms


MECHANISM_CAUSAL_CONFIRMED = "MECHANISM_CAUSAL_CONFIRMED"
MECHANISM_CAUSAL_UNCONFIRMED = "MECHANISM_CAUSAL_UNCONFIRMED"
MECHANISM_CAUSAL_STEP_UNAVAILABLE = "MECHANISM_CAUSAL_STEP_UNAVAILABLE"

_TIMESTAMP_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
)
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_CLI_TIMEOUT_OPTION_RE = re.compile(
    r"(?<!\\S)--?timeout(?:=(?:[^\\s`\"\']+)|\\s+[^\\s`\"\']+)",
    re.IGNORECASE,
)
_TRANSIENT_IDENTIFIER_RE = re.compile(
    r"\\b(?:[A-Za-z0-9_.]+[-_/])+(?:timeout|econnreset|etimedout)"
    r"(?:[-_/][A-Za-z0-9_.]+)*\\b",
    re.IGNORECASE,
)



@dataclass(frozen=True)
class MechanismCausalityAssessment:
    status: str
    reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    failed_step: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status == MECHANISM_CAUSAL_CONFIRMED


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


def _mask_noncausal_mechanism_tokens(line: str) -> str:
    value = _CLI_TIMEOUT_OPTION_RE.sub(" <cli-timeout-option> ", line)
    value = _TRANSIENT_IDENTIFIER_RE.sub(" <transient-identifier> ", value)
    return value


def assess_mechanism_causality(
    job: dict,
    log_text: str,
) -> MechanismCausalityAssessment:
    """Bind transient mechanism evidence to the failed step and causal log context.

    This is research-only and never grants runtime rerun authority.
    """
    failed_steps = [
        step
        for step in (job.get("steps") or [])
        if str(step.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]
    if len(failed_steps) != 1:
        return MechanismCausalityAssessment(
            MECHANISM_CAUSAL_STEP_UNAVAILABLE,
            evidence=("Exactly one failed step is required for mechanism binding.",),
        )

    step = failed_steps[0]
    step_name = str(step.get("name") or "").strip()
    start = _parse_time(step.get("started_at"))
    end = _parse_time(step.get("completed_at"))
    if not step_name or start is None or end is None or end < start:
        return MechanismCausalityAssessment(
            MECHANISM_CAUSAL_STEP_UNAVAILABLE,
            failed_step=step_name,
            evidence=("Failed-step timing metadata is incomplete.",),
        )

    tolerance = timedelta(seconds=2)
    lower = start - tolerance
    upper = end + tolerance

    reasons: list[str] = []
    evidence: list[str] = []
    for raw_line in log_text.splitlines():
        timestamp = _line_timestamp(raw_line)
        if timestamp is None or timestamp < lower or timestamp > upper:
            continue
        if causal_evidence_role(raw_line) != CAUSAL:
            continue

        cleaned = _clean_line(raw_line)
        mechanism_text = _mask_noncausal_mechanism_tokens(cleaned)
        line_reasons, _matches = detect_transient_mechanisms(mechanism_text)
        if not line_reasons:
            continue

        reasons.extend(line_reasons)
        if cleaned and cleaned not in evidence:
            evidence.append(cleaned)

    if reasons:
        return MechanismCausalityAssessment(
            MECHANISM_CAUSAL_CONFIRMED,
            reasons=tuple(dict.fromkeys(reasons)),
            evidence=tuple(evidence[:3]),
            failed_step=step_name,
        )

    return MechanismCausalityAssessment(
        MECHANISM_CAUSAL_UNCONFIRMED,
        failed_step=step_name,
        evidence=(
            "No transient mechanism appeared in causal evidence inside the failed-step window.",
        ),
    )
