from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ci_retry_gate import TRANSIENT_CATEGORIES
from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)


TARGET_MECHANISM = "SERVER_5XX"


@dataclass(frozen=True)
class Server5xxCounterexampleMatch:
    repository: str
    run_id: int
    job_name: str
    category: str
    confidence: str
    recovery_status: str
    side_effect_risk: bool
    signature: str
    evidence: tuple[str, ...] = ()

    @property
    def outcome_counterexample(self) -> bool:
        return self.recovery_status == RECOVERY_NOT_RECOVERED

    @property
    def classification_contradiction(self) -> bool:
        return self.category not in TRANSIENT_CATEGORIES and self.category != "UNKNOWN"


@dataclass(frozen=True)
class Server5xxCounterexampleSummary:
    matches: tuple[Server5xxCounterexampleMatch, ...]
    evaluable_matches: tuple[Server5xxCounterexampleMatch, ...]
    validated_recoveries: int
    failed_again: int
    unknown_outcomes: int
    outcome_counterexamples: tuple[Server5xxCounterexampleMatch, ...]
    classification_contradictions: tuple[Server5xxCounterexampleMatch, ...]
    side_effect_matches: int
    independent_runs: int
    independent_repositories: int
    category_counts: tuple[tuple[str, int], ...]
    repositories: tuple[str, ...]
    run_ids: tuple[int, ...]

    @property
    def observed_recovery_rate(self) -> float:
        if not self.evaluable_matches:
            return 0.0
        return self.validated_recoveries / len(self.evaluable_matches)


def search_server5xx_counterexamples(
    histories: dict[str, tuple[list[HistoricalFailure], int]],
) -> Server5xxCounterexampleSummary:
    matches: list[Server5xxCounterexampleMatch] = []

    for repository, (failures, _runs) in histories.items():
        for item in failures:
            if item.mechanism_causality_status != MECHANISM_CAUSAL_CONFIRMED:
                continue
            if TARGET_MECHANISM not in item.mechanism_causality_reasons:
                continue

            matches.append(
                Server5xxCounterexampleMatch(
                    repository=repository,
                    run_id=item.run_id,
                    job_name=item.job_name,
                    category=item.category,
                    confidence=item.confidence,
                    recovery_status=item.recovery_status,
                    side_effect_risk=item.side_effect_risk,
                    signature=item.signature or f"{item.category.lower()} without stable evidence",
                    evidence=item.mechanism_causal_evidence,
                )
            )

    matches.sort(
        key=lambda item: (
            item.repository,
            item.run_id,
            item.job_name,
            item.category,
        )
    )
    evaluable = tuple(
        item for item in matches if is_ground_truth_evaluable(item.recovery_status)
    )
    outcome_counterexamples = tuple(
        item for item in evaluable if item.outcome_counterexample
    )
    classification_contradictions = tuple(
        item for item in matches if item.classification_contradiction
    )
    run_ids = tuple(sorted({item.run_id for item in evaluable}))
    repositories = tuple(sorted({item.repository for item in evaluable}))
    category_counts = tuple(sorted(Counter(item.category for item in matches).items()))

    return Server5xxCounterexampleSummary(
        matches=tuple(matches),
        evaluable_matches=evaluable,
        validated_recoveries=sum(
            is_validated_recovery(item.recovery_status) for item in evaluable
        ),
        failed_again=len(outcome_counterexamples),
        unknown_outcomes=sum(
            not is_ground_truth_evaluable(item.recovery_status) for item in matches
        ),
        outcome_counterexamples=outcome_counterexamples,
        classification_contradictions=classification_contradictions,
        side_effect_matches=sum(item.side_effect_risk for item in matches),
        independent_runs=len(run_ids),
        independent_repositories=len(repositories),
        category_counts=category_counts,
        repositories=repositories,
        run_ids=run_ids,
    )


def render_server5xx_counterexample_report(
    summary: Server5xxCounterexampleSummary,
) -> str:
    lines = [
        "## SERVER_5XX Counterexample Search",
        "",
        "> Read-only falsification search across every runtime category. "
        "No classifier rule or rerun authority is changed.",
        "",
        f"- Causal SERVER_5XX matches: **{len(summary.matches)}**",
        f"- Ground-truth-evaluable matches: **{len(summary.evaluable_matches)}**",
        f"- Validated recoveries: **{summary.validated_recoveries}**",
        f"- Failed again outcome counterexamples: **{summary.failed_again}**",
        f"- Unknown/unverified outcomes: **{summary.unknown_outcomes}**",
        f"- Observed recovery rate: **{summary.observed_recovery_rate:.2%}**",
        f"- Classification-contradiction candidates: **{len(summary.classification_contradictions)}**",
        f"- Side-effect matches (authority signal only): **{summary.side_effect_matches}**",
        f"- Independent evaluable runs: **{summary.independent_runs}**",
        f"- Independent evaluable repositories: **{summary.independent_repositories}**",
        "",
        "### Category distribution",
        "",
    ]
    if summary.category_counts:
        for category, count in summary.category_counts:
            lines.append(f"- `{category}`: **{count}**")
    else:
        lines.append("- No causal SERVER_5XX match found.")

    lines.extend(
        [
            "",
            "### Evaluable matches",
            "",
            "| Repository | Run | Job | Category | Outcome | Side effect | Signature |",
            "|---|---:|---|---|---|---|---|",
        ]
    )
    for item in summary.evaluable_matches:
        lines.append(
            f"| {item.repository} | {item.run_id} | {item.job_name.replace('|', '/')} | "
            f"`{item.category}` | `{item.recovery_status}` | "
            f"{'yes' if item.side_effect_risk else 'no'} | "
            f"{item.signature.replace('|', '/')} |"
        )
    if not summary.evaluable_matches:
        lines.append("| — | — | — | — | — | — | No evaluable match |")

    if summary.outcome_counterexamples:
        lines.extend(["", "### Outcome counterexamples", ""])
        for item in summary.outcome_counterexamples:
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}, "
                f"category {item.category}: rerun failed again."
            )

    if summary.classification_contradictions:
        lines.extend(["", "### Classification contradictions", ""])
        for item in summary.classification_contradictions:
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}: "
                f"causal SERVER_5XX coexists with non-transient category "
                f"`{item.category}`."
            )

    lines.extend(
        [
            "",
            "> A contradiction candidate is diagnostic evidence for manual inspection, "
            "not proof that the proposed rule is wrong. The strongest falsifier is a "
            "ground-truth-evaluable causal SERVER_5XX match that fails again on rerun.",
        ]
    )
    return "\n".join(lines) + "\n"
