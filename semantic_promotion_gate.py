from __future__ import annotations

import re
from dataclasses import dataclass


SEMANTIC_PROMOTION_ELIGIBLE = "SEMANTIC_EVIDENCE_ELIGIBLE"
SEMANTIC_PROMOTION_BLOCKED = "SEMANTIC_EVIDENCE_BLOCKED"

REASON_GENERIC_RUNNER_WRAPPER = "GENERIC_RUNNER_WRAPPER"
REASON_GENERIC_CANCELLATION = "GENERIC_CANCELLATION"
REASON_SUCCESSFUL_TEST_LINE = "SUCCESSFUL_TEST_LINE"
REASON_COMMAND_SOURCE_TEXT = "COMMAND_SOURCE_TEXT"
REASON_NO_SPECIFIC_FAILURE = "NO_SPECIFIC_FAILURE_EVIDENCE"

_GENERIC_RUNNER_WRAPPERS = (
    re.compile(
        r"^(?:##\[error\]\s*)?process completed with exit code\s+<n>\.?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:##\[error\]\s*)?the operation was cancel(?:ed|led)\.?$",
        re.IGNORECASE,
    ),
)
_SUCCESSFUL_TEST_RE = re.compile(
    r"^test\b.*\.\.\.\s+ok$",
    re.IGNORECASE,
)
_COMMAND_SOURCE_RE = re.compile(
    r"^(?:printf|echo)\b.*(?:error|fatal|failed|failure|cannot|could not|"
    r"command not found|no such file)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SemanticPromotionAssessment:
    status: str
    accepted_segments: tuple[str, ...] = ()
    rejected_segments: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return self.status == SEMANTIC_PROMOTION_ELIGIBLE


def _segment_rejection_reason(segment: str) -> str | None:
    stripped = segment.strip()
    if not stripped:
        return REASON_NO_SPECIFIC_FAILURE

    for pattern in _GENERIC_RUNNER_WRAPPERS:
        if pattern.fullmatch(stripped):
            if "cancel" in stripped.lower():
                return REASON_GENERIC_CANCELLATION
            return REASON_GENERIC_RUNNER_WRAPPER

    if _SUCCESSFUL_TEST_RE.fullmatch(stripped):
        return REASON_SUCCESSFUL_TEST_LINE

    if _COMMAND_SOURCE_RE.search(stripped):
        return REASON_COMMAND_SOURCE_TEXT

    return None


def assess_semantic_promotion_signature(signature: str) -> SemanticPromotionAssessment:
    """Assess whether an UNKNOWN signature contains specific failure semantics.

    This gate is advisory-only. It never changes runtime classification or grants
    retry authority.
    """
    normalized = (signature or "").strip()
    if not normalized or normalized == "unknown without stable evidence":
        return SemanticPromotionAssessment(
            SEMANTIC_PROMOTION_BLOCKED,
            reasons=(REASON_NO_SPECIFIC_FAILURE,),
        )

    segments = tuple(
        segment.strip()
        for segment in normalized.split(" | ")
        if segment.strip()
    )
    if not segments:
        return SemanticPromotionAssessment(
            SEMANTIC_PROMOTION_BLOCKED,
            reasons=(REASON_NO_SPECIFIC_FAILURE,),
        )

    accepted: list[str] = []
    rejected: list[str] = []
    reasons: list[str] = []

    for segment in segments:
        reason = _segment_rejection_reason(segment)
        if reason is None:
            accepted.append(segment)
            continue
        rejected.append(segment)
        if reason not in reasons:
            reasons.append(reason)

    if accepted:
        return SemanticPromotionAssessment(
            SEMANTIC_PROMOTION_ELIGIBLE,
            accepted_segments=tuple(accepted),
            rejected_segments=tuple(rejected),
            reasons=tuple(reasons),
        )

    if not reasons:
        reasons.append(REASON_NO_SPECIFIC_FAILURE)

    return SemanticPromotionAssessment(
        SEMANTIC_PROMOTION_BLOCKED,
        accepted_segments=(),
        rejected_segments=tuple(rejected),
        reasons=tuple(reasons),
    )
