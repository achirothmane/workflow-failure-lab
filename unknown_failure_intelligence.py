from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass

from ci_retry_gate import redact
from history_ci_waste import HistoricalFailure, normalize_signature_line
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)
from semantic_promotion_gate import (
    SEMANTIC_PROMOTION_ELIGIBLE,
    assess_semantic_promotion_signature,
)
from transient_mechanism_gate import (
    MECHANISM_TRANSIENT_SUPPORTED,
    assess_transient_mechanism,
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RUNNER_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+"
)
_GENERIC_ERROR_RE = re.compile(
    r"(::error::|##\[error\]|"
    r"^(?:error|fatal|exception|panic|failed|failure)\b\s*[:\-]?|"
    r"segmentation fault|\btraceback\b|exit code|permission denied|"
    r"no such file|not found|unable to|cannot|could not|connection refused|"
    r"timed out|timeout)",
    re.IGNORECASE,
)
_BENIGN_METADATA_PATTERNS = (
    re.compile(r"^digest-mismatch:\s*(?:error|warn|warning|ignore)$", re.IGNORECASE),
)

MIN_UNKNOWN_OCCURRENCES = 3
MIN_UNKNOWN_RERUN_SAMPLES = 3
MIN_UNKNOWN_RECOVERY_RATE = 0.80

STATUS_INVESTIGATE_TRANSIENT = "INVESTIGATE_TRANSIENT_PATTERN"
STATUS_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
STATUS_SIDE_EFFECT_GUARDED = "SIDE_EFFECT_GUARDED"
STATUS_NOT_TRANSIENT = "NOT_TRANSIENT"

PROMOTION_BLOCKER_NO_STABLE_SIGNATURE = "NO_STABLE_SIGNATURE"
PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES = "INSUFFICIENT_OCCURRENCES"
PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS = "INSUFFICIENT_GT_RERUNS"
PROMOTION_BLOCKER_RECOVERY_RATE = "RECOVERY_RATE_BELOW_THRESHOLD"
PROMOTION_BLOCKER_SIDE_EFFECT = "SIDE_EFFECT_CONTAMINATION"
PROMOTION_BLOCKER_SEMANTIC_EVIDENCE = "SEMANTIC_EVIDENCE_QUALITY"
PROMOTION_BLOCKER_TRANSIENT_MECHANISM = "TRANSIENT_MECHANISM_EVIDENCE"
PROMOTION_ELIGIBLE = "ELIGIBLE_FOR_CLASSIFIER_RESEARCH"


@dataclass(frozen=True)
class UnknownPattern:
    pattern_id: str
    signature: str
    occurrences: int
    repositories: int
    rerun_observations: int
    recoveries: int
    failed_again: int
    unknown_outcomes: int
    side_effect_occurrences: int
    status: str
    promotion_blocker: str = PROMOTION_ELIGIBLE
    promotion_blockers: tuple[str, ...] = ()
    occurrence_deficit: int = 0
    gt_rerun_deficit: int = 0
    recovery_rate_deficit: float = 0.0
    semantic_status: str = SEMANTIC_PROMOTION_ELIGIBLE
    semantic_reasons: tuple[str, ...] = ()
    semantic_accepted_segments: tuple[str, ...] = ()
    semantic_rejected_segments: tuple[str, ...] = ()
    mechanism_status: str = ""
    mechanism_reasons: tuple[str, ...] = ()
    mechanism_evidence: tuple[str, ...] = ()
    mechanism_causes: tuple[str, ...] = ()

    @property
    def recovery_rate(self) -> float:
        if self.rerun_observations <= 0:
            return 0.0
        return self.recoveries / self.rerun_observations

    @property
    def repeated(self) -> bool:
        return self.occurrences >= 2

    @property
    def promotion_candidate(self) -> bool:
        return self.status == STATUS_INVESTIGATE_TRANSIENT

    @property
    def promotion_distance(self) -> int:
        return len(self.promotion_blockers)


@dataclass(frozen=True)
class UnknownCauseSummary:
    cause: str
    occurrences: int
    repositories: int
    rerun_observations: int
    recoveries: int
    failed_again: int
    unknown_outcomes: int
    side_effect_occurrences: int
    examples: tuple[str, ...] = ()

    @property
    def recovery_rate(self) -> float:
        if self.rerun_observations <= 0:
            return 0.0
        return self.recoveries / self.rerun_observations


@dataclass(frozen=True)
class UnknownIntelligenceSummary:
    unknown_failures: int
    patterns: tuple[UnknownPattern, ...]
    causes: tuple[UnknownCauseSummary, ...] = ()

    @property
    def repeated_patterns(self) -> int:
        return sum(item.repeated for item in self.patterns)

    @property
    def evaluated_reruns(self) -> int:
        return sum(item.rerun_observations for item in self.patterns)

    @property
    def recoveries(self) -> int:
        return sum(item.recoveries for item in self.patterns)

    @property
    def failed_again(self) -> int:
        return sum(item.failed_again for item in self.patterns)

    @property
    def unknown_outcomes(self) -> int:
        return sum(item.unknown_outcomes for item in self.patterns)

    @property
    def promotion_candidates(self) -> tuple[UnknownPattern, ...]:
        return tuple(item for item in self.patterns if item.promotion_candidate)

    @property
    def near_promotion_candidates(self) -> tuple[UnknownPattern, ...]:
        return tuple(
            item
            for item in self.patterns
            if not item.promotion_candidate and item.promotion_distance == 1
        )

    @property
    def promotion_blocker_counts(self) -> tuple[tuple[str, int], ...]:
        counts: dict[str, int] = defaultdict(int)
        for item in self.patterns:
            if item.promotion_candidate:
                counts[PROMOTION_ELIGIBLE] += 1
                continue
            for blocker in item.promotion_blockers:
                counts[blocker] += 1
        return tuple(
            sorted(
                counts.items(),
                key=lambda pair: (-pair[1], pair[0]),
            )
        )


def _semantic_log_content(raw_line: str) -> str:
    """Return the user/tool message without runner timestamps, ANSI, or benign metadata."""
    cleaned = redact(raw_line)
    cleaned = _ANSI_RE.sub("", cleaned)
    cleaned = _RUNNER_TIMESTAMP_RE.sub("", cleaned).strip()
    if not cleaned:
        return ""

    # Shell comments and GitHub runner grouping metadata frequently contain words like
    # "error" while describing behavior rather than reporting a failure.
    if cleaned.startswith("#") and not cleaned.startswith("##[error]"):
        return ""
    if cleaned.startswith(("##[group]", "##[endgroup]", "##[debug]")):
        return ""
    if any(pattern.fullmatch(cleaned) for pattern in _BENIGN_METADATA_PATTERNS):
        return ""
    return cleaned


def extract_unknown_evidence(log_text: str, limit: int = 3) -> tuple[str, ...]:
    """Extract redacted, semantically error-like lines when no known classifier rule matches."""
    hits: list[str] = []
    for raw_line in log_text.splitlines():
        cleaned = _semantic_log_content(raw_line)
        if not cleaned or not _GENERIC_ERROR_RE.search(cleaned):
            continue
        normalized = normalize_signature_line(cleaned)
        if not normalized or normalized in hits:
            continue
        hits.append(normalized[:220])
        if len(hits) >= limit:
            break
    return tuple(hits)


def unknown_signature(log_text: str) -> str:
    evidence = extract_unknown_evidence(log_text)
    if not evidence:
        return "unknown without stable evidence"
    return " | ".join(evidence[:2])


def unknown_pattern_id(signature: str) -> str:
    normalized = normalize_signature_line(signature)
    digest = hashlib.sha256(f"UNKNOWN\n{normalized}".encode("utf-8")).hexdigest()[:12].upper()
    return f"UF-{digest}"


def _promotion_blockers_for(
    occurrences: int,
    rerun_observations: int,
    recoveries: int,
    side_effect_occurrences: int,
    signature: str,
    causes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    blockers: list[str] = []
    semantic = assess_semantic_promotion_signature(signature)
    mechanism = assess_transient_mechanism(signature, causes)
    if signature == "unknown without stable evidence":
        blockers.append(PROMOTION_BLOCKER_NO_STABLE_SIGNATURE)
    if not semantic.eligible:
        blockers.append(PROMOTION_BLOCKER_SEMANTIC_EVIDENCE)
    if not mechanism.supported:
        blockers.append(PROMOTION_BLOCKER_TRANSIENT_MECHANISM)
    if occurrences < MIN_UNKNOWN_OCCURRENCES:
        blockers.append(PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES)
    if rerun_observations < MIN_UNKNOWN_RERUN_SAMPLES:
        blockers.append(PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS)
    if rerun_observations >= MIN_UNKNOWN_RERUN_SAMPLES:
        recovery_rate = recoveries / rerun_observations
        if recovery_rate < MIN_UNKNOWN_RECOVERY_RATE:
            blockers.append(PROMOTION_BLOCKER_RECOVERY_RATE)
    if side_effect_occurrences:
        blockers.append(PROMOTION_BLOCKER_SIDE_EFFECT)
    return tuple(blockers)


def _status_for(
    occurrences: int,
    rerun_observations: int,
    recoveries: int,
    side_effect_occurrences: int,
    signature: str,
    causes: tuple[str, ...] = (),
) -> str:
    if side_effect_occurrences:
        return STATUS_SIDE_EFFECT_GUARDED
    if signature == "unknown without stable evidence":
        return STATUS_INSUFFICIENT_EVIDENCE
    if not assess_semantic_promotion_signature(signature).eligible:
        return STATUS_INSUFFICIENT_EVIDENCE
    if not assess_transient_mechanism(signature, causes).supported:
        return STATUS_INSUFFICIENT_EVIDENCE
    if occurrences < MIN_UNKNOWN_OCCURRENCES or rerun_observations < MIN_UNKNOWN_RERUN_SAMPLES:
        return STATUS_INSUFFICIENT_EVIDENCE
    recovery_rate = recoveries / rerun_observations if rerun_observations else 0.0
    if recovery_rate >= MIN_UNKNOWN_RECOVERY_RATE:
        return STATUS_INVESTIGATE_TRANSIENT
    return STATUS_NOT_TRANSIENT


def summarize_unknown_patterns(
    histories: dict[str, tuple[list[HistoricalFailure], int]],
    rerun_histories: dict[str, tuple[list[HistoricalFailure], int]],
) -> UnknownIntelligenceSummary:
    occurrences: dict[str, int] = defaultdict(int)
    repos: dict[str, set[str]] = defaultdict(set)
    rerun_observations: dict[str, int] = defaultdict(int)
    recoveries: dict[str, int] = defaultdict(int)
    failed_again: dict[str, int] = defaultdict(int)
    unknown_outcomes: dict[str, int] = defaultdict(int)
    side_effect_occurrences: dict[str, int] = defaultdict(int)
    signatures: dict[str, str] = {}
    pattern_causes: dict[str, set[str]] = defaultdict(set)

    cause_occurrences: dict[str, int] = defaultdict(int)
    cause_repos: dict[str, set[str]] = defaultdict(set)
    cause_rerun_observations: dict[str, int] = defaultdict(int)
    cause_recoveries: dict[str, int] = defaultdict(int)
    cause_failed_again: dict[str, int] = defaultdict(int)
    cause_unknown_outcomes: dict[str, int] = defaultdict(int)
    cause_side_effect_occurrences: dict[str, int] = defaultdict(int)
    cause_examples: dict[str, list[str]] = defaultdict(list)

    # Natural and rerun-enriched samples are intentionally disjoint in Benchmark Mode.
    for source, is_rerun_sample in ((histories, False), (rerun_histories, True)):
        for repo, (failures, _runs) in source.items():
            for item in failures:
                if item.category != "UNKNOWN":
                    continue
                signature = item.signature or "unknown without stable evidence"
                pattern_id = unknown_pattern_id(signature)
                signatures[pattern_id] = signature
                occurrences[pattern_id] += 1
                repos[pattern_id].add(repo)

                cause = item.unknown_cause or "UNDECOMPOSED"
                pattern_causes[pattern_id].add(cause)
                cause_occurrences[cause] += 1
                cause_repos[cause].add(repo)
                if signature not in cause_examples[cause] and len(cause_examples[cause]) < 3:
                    cause_examples[cause].append(signature)

                if item.side_effect_risk:
                    side_effect_occurrences[pattern_id] += 1
                    cause_side_effect_occurrences[cause] += 1
                if is_rerun_sample:
                    if is_ground_truth_evaluable(item.recovery_status):
                        rerun_observations[pattern_id] += 1
                        cause_rerun_observations[cause] += 1
                        if is_validated_recovery(item.recovery_status):
                            recoveries[pattern_id] += 1
                            cause_recoveries[cause] += 1
                        elif item.recovery_status == RECOVERY_NOT_RECOVERED:
                            failed_again[pattern_id] += 1
                            cause_failed_again[cause] += 1
                    else:
                        unknown_outcomes[pattern_id] += 1
                        cause_unknown_outcomes[cause] += 1

    patterns: list[UnknownPattern] = []
    for pattern_id, count in occurrences.items():
        signature = signatures[pattern_id]
        causes = tuple(sorted(pattern_causes[pattern_id]))
        semantic = assess_semantic_promotion_signature(signature)
        mechanism = assess_transient_mechanism(signature, causes)
        blockers = _promotion_blockers_for(
            count,
            rerun_observations[pattern_id],
            recoveries[pattern_id],
            side_effect_occurrences[pattern_id],
            signature,
            causes,
        )
        recovery_rate = (
            recoveries[pattern_id] / rerun_observations[pattern_id]
            if rerun_observations[pattern_id]
            else 0.0
        )
        patterns.append(
            UnknownPattern(
                pattern_id=pattern_id,
                signature=signature,
                occurrences=count,
                repositories=len(repos[pattern_id]),
                rerun_observations=rerun_observations[pattern_id],
                recoveries=recoveries[pattern_id],
                failed_again=failed_again[pattern_id],
                unknown_outcomes=unknown_outcomes[pattern_id],
                side_effect_occurrences=side_effect_occurrences[pattern_id],
                status=_status_for(
                    count,
                    rerun_observations[pattern_id],
                    recoveries[pattern_id],
                    side_effect_occurrences[pattern_id],
                    signature,
                    causes,
                ),
                promotion_blocker=(
                    blockers[0] if blockers else PROMOTION_ELIGIBLE
                ),
                promotion_blockers=blockers,
                occurrence_deficit=max(0, MIN_UNKNOWN_OCCURRENCES - count),
                gt_rerun_deficit=max(
                    0,
                    MIN_UNKNOWN_RERUN_SAMPLES - rerun_observations[pattern_id],
                ),
                recovery_rate_deficit=max(
                    0.0,
                    MIN_UNKNOWN_RECOVERY_RATE - recovery_rate,
                ),
                semantic_status=semantic.status,
                semantic_reasons=semantic.reasons,
                semantic_accepted_segments=semantic.accepted_segments,
                semantic_rejected_segments=semantic.rejected_segments,
                mechanism_status=mechanism.status,
                mechanism_reasons=mechanism.reasons,
                mechanism_evidence=mechanism.transient_evidence,
                mechanism_causes=causes,
            )
        )

    patterns.sort(
        key=lambda item: (
            not item.promotion_candidate,
            item.promotion_distance,
            -item.rerun_observations,
            -item.occurrences,
            -item.repositories,
            item.pattern_id,
        )
    )

    causes = [
        UnknownCauseSummary(
            cause=cause,
            occurrences=count,
            repositories=len(cause_repos[cause]),
            rerun_observations=cause_rerun_observations[cause],
            recoveries=cause_recoveries[cause],
            failed_again=cause_failed_again[cause],
            unknown_outcomes=cause_unknown_outcomes[cause],
            side_effect_occurrences=cause_side_effect_occurrences[cause],
            examples=tuple(cause_examples[cause]),
        )
        for cause, count in cause_occurrences.items()
    ]
    causes.sort(
        key=lambda item: (
            -item.occurrences,
            -item.rerun_observations,
            item.cause,
        )
    )

    return UnknownIntelligenceSummary(
        unknown_failures=sum(occurrences.values()),
        patterns=tuple(patterns),
        causes=tuple(causes),
    )
