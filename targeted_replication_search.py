from __future__ import annotations

from dataclasses import dataclass

from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)
from unknown_failure_intelligence import unknown_pattern_id


@dataclass(frozen=True)
class ReplicationMatch:
    repository: str
    run_id: int
    job_name: str
    pattern_id: str
    signature: str
    recovery_status: str
    side_effect_risk: bool
    mechanism_reasons: tuple[str, ...]
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class TargetedReplicationSummary:
    mechanism_reason: str
    matches: tuple[ReplicationMatch, ...]
    usable_matches: tuple[ReplicationMatch, ...]
    independent_runs: int
    independent_repositories: int
    validated_recoveries: int
    failed_again: int
    side_effect_contaminated: int
    pattern_ids: tuple[str, ...]
    repositories: tuple[str, ...]
    run_ids: tuple[int, ...]

    @property
    def replicated(self) -> bool:
        return self.independent_runs >= 2

    @property
    def cross_repository_replicated(self) -> bool:
        return self.independent_repositories >= 2

    @property
    def recovery_rate(self) -> float:
        evaluated = self.validated_recoveries + self.failed_again
        if evaluated <= 0:
            return 0.0
        return self.validated_recoveries / evaluated


def search_targeted_replication(
    histories: dict[str, tuple[list[HistoricalFailure], int]],
    mechanism_reason: str,
) -> TargetedReplicationSummary:
    target = mechanism_reason.strip().upper()
    matches: list[ReplicationMatch] = []

    for repository, (failures, _runs) in histories.items():
        for item in failures:
            if item.category != "UNKNOWN":
                continue
            if item.mechanism_causality_status != MECHANISM_CAUSAL_CONFIRMED:
                continue
            if target not in {reason.upper() for reason in item.mechanism_causality_reasons}:
                continue
            if not is_ground_truth_evaluable(item.recovery_status):
                continue

            signature = item.signature or "unknown without stable evidence"
            matches.append(
                ReplicationMatch(
                    repository=repository,
                    run_id=item.run_id,
                    job_name=item.job_name,
                    pattern_id=unknown_pattern_id(signature),
                    signature=signature,
                    recovery_status=item.recovery_status,
                    side_effect_risk=item.side_effect_risk,
                    mechanism_reasons=item.mechanism_causality_reasons,
                    evidence=item.mechanism_causal_evidence,
                )
            )

    matches.sort(
        key=lambda item: (
            item.repository,
            item.run_id,
            item.job_name,
            item.pattern_id,
        )
    )
    usable = tuple(item for item in matches if not item.side_effect_risk)
    run_ids = tuple(sorted({item.run_id for item in usable}))
    repositories = tuple(sorted({item.repository for item in usable}))
    pattern_ids = tuple(sorted({item.pattern_id for item in usable}))

    return TargetedReplicationSummary(
        mechanism_reason=target,
        matches=tuple(matches),
        usable_matches=usable,
        independent_runs=len(run_ids),
        independent_repositories=len(repositories),
        validated_recoveries=sum(
            is_validated_recovery(item.recovery_status) for item in usable
        ),
        failed_again=sum(
            item.recovery_status == RECOVERY_NOT_RECOVERED for item in usable
        ),
        side_effect_contaminated=sum(item.side_effect_risk for item in matches),
        pattern_ids=pattern_ids,
        repositories=repositories,
        run_ids=run_ids,
    )



def render_targeted_replication_report(summary: TargetedReplicationSummary) -> str:
    lines = [
        "## Targeted Replication Search",
        "",
        f"- Mechanism: `{summary.mechanism_reason}`",
        f"- Usable causal GT matches: **{len(summary.usable_matches)}**",
        f"- Independent workflow runs: **{summary.independent_runs}**",
        f"- Independent repositories: **{summary.independent_repositories}**",
        f"- Validated recoveries: **{summary.validated_recoveries}**",
        f"- Failed again: **{summary.failed_again}**",
        f"- Ground-truth recovery rate: **{summary.recovery_rate:.1%}**",
        f"- Side-effect contaminated matches excluded from replication: **{summary.side_effect_contaminated}**",
        f"- Independent replication confirmed: **{'YES' if summary.replicated else 'no'}**",
        f"- Cross-repository replication: **{'YES' if summary.cross_repository_replicated else 'no'}**",
        "",
        "| Repository | Run | Job | Pattern | Outcome | Signature |",
        "|---|---:|---|---|---|---|",
    ]
    for item in summary.usable_matches:
        signature = item.signature.replace("|", "/")
        lines.append(
            f"| {item.repository} | {item.run_id} | {item.job_name.replace('|', '/')} | "
            f"`{item.pattern_id}` | `{item.recovery_status}` | {signature} |"
        )
    if not summary.usable_matches:
        lines.append("| — | — | — | — | — | No qualifying causal ground-truth match found |")
    lines.extend(
        [
            "",
            "> Mechanism-family replication is research evidence only. It does not "
            "promote a runtime classifier rule and does not grant rerun authority.",
        ]
    )
    return "\n".join(lines) + "\n"
