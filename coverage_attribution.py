from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ci_retry_gate import PROVENANCE_CONFIRMED, TRANSIENT_CATEGORIES
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_validated_recovery,
)


GATE_CLASSIFICATION_UNKNOWN = "CLASSIFICATION_UNKNOWN"
GATE_NON_TRANSIENT_CATEGORY = "NON_TRANSIENT_CATEGORY"
GATE_CODE_REGRESSION = "CODE_REGRESSION"
GATE_CAUSAL_EVIDENCE = "INSUFFICIENT_CAUSAL_EVIDENCE"
GATE_LOW_CONFIDENCE = "LOW_TRANSIENT_CONFIDENCE"
GATE_PROVENANCE = "UNCONFIRMED_EXECUTION_PROVENANCE"
GATE_SIDE_EFFECT = "SIDE_EFFECT_BOUNDARY"
GATE_ELIGIBLE = "ELIGIBLE"

KIND_EVIDENCE_GAP = "EVIDENCE_GAP"
KIND_DETERMINISTIC_BLOCKER = "DETERMINISTIC_BLOCKER"
KIND_POLICY_BOUNDARY = "POLICY_BOUNDARY"
KIND_AUTHORITY_BOUNDARY = "AUTHORITY_BOUNDARY"
KIND_ELIGIBLE = "ELIGIBLE"

_GATE_ORDER = {
    GATE_CLASSIFICATION_UNKNOWN: 0,
    GATE_NON_TRANSIENT_CATEGORY: 1,
    GATE_CODE_REGRESSION: 2,
    GATE_CAUSAL_EVIDENCE: 3,
    GATE_LOW_CONFIDENCE: 4,
    GATE_PROVENANCE: 5,
    GATE_SIDE_EFFECT: 6,
    GATE_ELIGIBLE: 7,
}


@dataclass(frozen=True)
class CoverageAttribution:
    gate: str
    kind: str
    detail: str


@dataclass(frozen=True)
class CoverageGateSummary:
    gate: str
    kind: str
    failures: int
    raw_later_successes: int
    validated_recoveries: int
    failed_reruns: int
    unknown_or_unverified: int

    @property
    def raw_later_success_rate(self) -> float:
        if self.failures <= 0:
            return 0.0
        return self.raw_later_successes / self.failures


def first_coverage_gate(item) -> CoverageAttribution:
    """Return the first limiting layer in the safety pipeline for one failure.

    This is diagnostic only. It does not grant rerun authority or weaken any
    production gate.
    """
    category = str(item.category or "")
    confidence = str(item.confidence or "")

    if category == "UNKNOWN":
        return CoverageAttribution(
            GATE_CLASSIFICATION_UNKNOWN,
            KIND_EVIDENCE_GAP,
            "No known failure category reached the classifier threshold.",
        )

    if category == "CODE_REGRESSION":
        return CoverageAttribution(
            GATE_CODE_REGRESSION,
            KIND_DETERMINISTIC_BLOCKER,
            "The failure is classified as a code regression.",
        )

    if category not in TRANSIENT_CATEGORIES:
        return CoverageAttribution(
            GATE_NON_TRANSIENT_CATEGORY,
            KIND_POLICY_BOUNDARY,
            f"{category} is outside the conservative transient allow-list.",
        )

    if confidence != "high":
        causal_count = int(getattr(item, "causal_evidence_count", 0) or 0)
        if causal_count <= 0:
            return CoverageAttribution(
                GATE_CAUSAL_EVIDENCE,
                KIND_EVIDENCE_GAP,
                "Transient evidence exists, but none of the selected classifier evidence is directly causal.",
            )
        return CoverageAttribution(
            GATE_LOW_CONFIDENCE,
            KIND_EVIDENCE_GAP,
            f"Transient classification confidence is {confidence}, not high.",
        )

    if str(item.provenance_status or "") != PROVENANCE_CONFIRMED:
        return CoverageAttribution(
            GATE_PROVENANCE,
            KIND_EVIDENCE_GAP,
            f"Execution provenance is {item.provenance_status}, not confirmed.",
        )

    if bool(item.side_effect_risk):
        return CoverageAttribution(
            GATE_SIDE_EFFECT,
            KIND_AUTHORITY_BOUNDARY,
            "The workflow crosses a deploy/publish/push/PR or other side-effect boundary.",
        )

    return CoverageAttribution(
        GATE_ELIGIBLE,
        KIND_ELIGIBLE,
        "The failure passes classification, confidence, provenance, and authority gates.",
    )


def summarize_coverage_attribution(failures: list) -> tuple[CoverageGateSummary, ...]:
    counts: Counter[str] = Counter()
    raw_successes: Counter[str] = Counter()
    validated: Counter[str] = Counter()
    failed_reruns: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    kinds: dict[str, str] = {}

    for item in failures:
        attribution = first_coverage_gate(item)
        gate = attribution.gate
        kinds[gate] = attribution.kind
        counts[gate] += 1

        if bool(item.rerun_observed) and bool(item.recovered_after_rerun):
            raw_successes[gate] += 1

        if is_validated_recovery(str(item.recovery_status or "")):
            validated[gate] += 1
        elif str(item.recovery_status or "") == RECOVERY_NOT_RECOVERED:
            failed_reruns[gate] += 1
        else:
            unknown[gate] += 1

    rows = [
        CoverageGateSummary(
            gate=gate,
            kind=kinds[gate],
            failures=count,
            raw_later_successes=raw_successes[gate],
            validated_recoveries=validated[gate],
            failed_reruns=failed_reruns[gate],
            unknown_or_unverified=unknown[gate],
        )
        for gate, count in counts.items()
    ]
    rows.sort(key=lambda item: (_GATE_ORDER.get(item.gate, 999), item.gate))
    return tuple(rows)


def coverage_gate_count(
    summaries: tuple[CoverageGateSummary, ...],
    gate: str,
) -> int:
    for item in summaries:
        if item.gate == gate:
            return item.failures
    return 0


def evidence_gap_count(summaries: tuple[CoverageGateSummary, ...]) -> int:
    return sum(item.failures for item in summaries if item.kind == KIND_EVIDENCE_GAP)
