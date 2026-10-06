from __future__ import annotations

from dataclasses import dataclass

from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)


RULE_SERVER_5XX_CAUSAL_UNKNOWN = "SERVER_5XX_CAUSAL_UNKNOWN"
PROPOSED_CATEGORY = "DEPENDENCY_NETWORK"
TARGET_MECHANISM = "SERVER_5XX"


@dataclass(frozen=True)
class Server5xxRuleMatch:
    repository: str
    run_id: int
    job_name: str
    recovery_status: str
    side_effect_risk: bool
    signature: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Server5xxRuleResearchSummary:
    rule_name: str
    proposed_category: str
    natural_unknown_failures: int
    natural_matches: tuple[Server5xxRuleMatch, ...]
    rerun_matches: tuple[Server5xxRuleMatch, ...]
    evaluable_matches: int
    validated_recoveries: int
    failed_again: int
    unknown_outcomes: int
    side_effect_matches: int
    independent_runs: int
    independent_repositories: int
    repositories: tuple[str, ...]
    run_ids: tuple[int, ...]

    @property
    def natural_match_rate(self) -> float:
        if self.natural_unknown_failures <= 0:
            return 0.0
        return len(self.natural_matches) / self.natural_unknown_failures

    @property
    def observed_precision(self) -> float:
        if self.evaluable_matches <= 0:
            return 0.0
        return self.validated_recoveries / self.evaluable_matches

    @property
    def authority_safe_matches(self) -> int:
        return sum(not item.side_effect_risk for item in self.rerun_matches)

    @property
    def authority_blocked_matches(self) -> int:
        return self.side_effect_matches

    @property
    def false_positive_matches(self) -> tuple[Server5xxRuleMatch, ...]:
        return tuple(
            item
            for item in self.rerun_matches
            if item.recovery_status == RECOVERY_NOT_RECOVERED
        )


def _matches_rule(item: HistoricalFailure) -> bool:
    return (
        item.category == "UNKNOWN"
        and item.mechanism_causality_status == MECHANISM_CAUSAL_CONFIRMED
        and TARGET_MECHANISM in item.mechanism_causality_reasons
    )


def _match(repository: str, item: HistoricalFailure) -> Server5xxRuleMatch:
    return Server5xxRuleMatch(
        repository=repository,
        run_id=item.run_id,
        job_name=item.job_name,
        recovery_status=item.recovery_status,
        side_effect_risk=item.side_effect_risk,
        signature=item.signature or "unknown without stable evidence",
        evidence=item.mechanism_causal_evidence,
    )


def evaluate_server5xx_shadow_rule(
    natural_histories: dict[str, tuple[list[HistoricalFailure], int]],
    rerun_histories: dict[str, tuple[list[HistoricalFailure], int]],
) -> Server5xxRuleResearchSummary:
    natural_unknown_failures = 0
    natural_matches: list[Server5xxRuleMatch] = []
    rerun_matches: list[Server5xxRuleMatch] = []

    for repository, (failures, _runs) in natural_histories.items():
        for item in failures:
            if item.category == "UNKNOWN":
                natural_unknown_failures += 1
            if _matches_rule(item):
                natural_matches.append(_match(repository, item))

    for repository, (failures, _runs) in rerun_histories.items():
        for item in failures:
            if _matches_rule(item):
                rerun_matches.append(_match(repository, item))

    natural_matches.sort(key=lambda item: (item.repository, item.run_id, item.job_name))
    rerun_matches.sort(key=lambda item: (item.repository, item.run_id, item.job_name))

    evaluable = [
        item for item in rerun_matches if is_ground_truth_evaluable(item.recovery_status)
    ]
    run_ids = tuple(sorted({item.run_id for item in evaluable}))
    repositories = tuple(sorted({item.repository for item in evaluable}))

    return Server5xxRuleResearchSummary(
        rule_name=RULE_SERVER_5XX_CAUSAL_UNKNOWN,
        proposed_category=PROPOSED_CATEGORY,
        natural_unknown_failures=natural_unknown_failures,
        natural_matches=tuple(natural_matches),
        rerun_matches=tuple(rerun_matches),
        evaluable_matches=len(evaluable),
        validated_recoveries=sum(
            is_validated_recovery(item.recovery_status) for item in evaluable
        ),
        failed_again=sum(
            item.recovery_status == RECOVERY_NOT_RECOVERED for item in evaluable
        ),
        unknown_outcomes=sum(
            not is_ground_truth_evaluable(item.recovery_status)
            for item in rerun_matches
        ),
        side_effect_matches=sum(item.side_effect_risk for item in rerun_matches),
        independent_runs=len(run_ids),
        independent_repositories=len(repositories),
        repositories=repositories,
        run_ids=run_ids,
    )


def render_server5xx_rule_research(summary: Server5xxRuleResearchSummary) -> str:
    lines = [
        "## SERVER_5XX Classifier Rule Research",
        "",
        "> Shadow-only classifier hypothesis. This report does not modify classify_log(), "
        "does not change runtime categories, and does not grant rerun authority.",
        "",
        f"- Rule: `{summary.rule_name}`",
        f"- Proposed category: `{summary.proposed_category}`",
        f"- Natural UNKNOWN failures: **{summary.natural_unknown_failures}**",
        f"- Natural shadow matches: **{len(summary.natural_matches)}**",
        f"- Natural UNKNOWN match rate: **{summary.natural_match_rate:.2%}**",
        f"- Rerun-enriched shadow matches: **{len(summary.rerun_matches)}**",
        f"- Ground-truth-evaluable matches: **{summary.evaluable_matches}**",
        f"- Validated recoveries: **{summary.validated_recoveries}**",
        f"- Failed again: **{summary.failed_again}**",
        f"- Unknown/unverified outcomes: **{summary.unknown_outcomes}**",
        f"- Observed classifier-hypothesis precision: **{summary.observed_precision:.2%}**",
        f"- Independent evaluable runs: **{summary.independent_runs}**",
        f"- Independent evaluable repositories: **{summary.independent_repositories}**",
        f"- Side-effect matches (authority-blocked, not classifier false positives): **{summary.side_effect_matches}**",
        "",
        "### Ground-truth matches",
        "",
        "| Repository | Run | Job | Outcome | Side effect | Signature |",
        "|---|---:|---|---|---|---|",
    ]

    evaluable_rows = [
        item
        for item in summary.rerun_matches
        if is_ground_truth_evaluable(item.recovery_status)
    ]
    for item in evaluable_rows:
        signature = item.signature.replace("|", "/")
        lines.append(
            f"| {item.repository} | {item.run_id} | {item.job_name.replace('|', '/')} | "
            f"`{item.recovery_status}` | {'yes' if item.side_effect_risk else 'no'} | "
            f"{signature} |"
        )
    if not evaluable_rows:
        lines.append("| — | — | — | — | — | No evaluable shadow match |")

    if summary.false_positive_matches:
        lines.extend(
            [
                "",
                "### False-positive candidates",
                "",
            ]
        )
        for item in summary.false_positive_matches:
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}: "
                f"{item.signature}"
            )

    lines.extend(
        [
            "",
            "> A validated recovery supports the transient-classifier hypothesis but is "
            "not sufficient by itself for production promotion. Runtime authority remains "
            "subject to the existing provenance, side-effect, retry-cap, and policy gates.",
        ]
    )
    return "\n".join(lines) + "\n"
