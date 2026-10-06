from __future__ import annotations

from dataclasses import dataclass


REPLICATION_CONFIRMED = "INDEPENDENT_REPLICATION_CONFIRMED"
REPLICATION_INSUFFICIENT = "INDEPENDENT_REPLICATION_INSUFFICIENT"

MIN_INDEPENDENT_RUNS = 2


@dataclass(frozen=True)
class IndependentReplicationAssessment:
    status: str
    independent_runs: int
    independent_repositories: int
    run_ids: tuple[int, ...] = ()
    repositories: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.status == REPLICATION_CONFIRMED

    @property
    def cross_repository(self) -> bool:
        return self.independent_repositories >= 2

    @property
    def run_deficit(self) -> int:
        return max(0, MIN_INDEPENDENT_RUNS - self.independent_runs)


def assess_independent_replication(
    run_ids: set[int] | tuple[int, ...],
    repositories: set[str] | tuple[str, ...],
) -> IndependentReplicationAssessment:
    normalized_runs = tuple(sorted({int(run_id) for run_id in run_ids if int(run_id) > 0}))
    normalized_repositories = tuple(
        sorted({repo.strip() for repo in repositories if repo and repo.strip()})
    )
    status = (
        REPLICATION_CONFIRMED
        if len(normalized_runs) >= MIN_INDEPENDENT_RUNS
        else REPLICATION_INSUFFICIENT
    )
    return IndependentReplicationAssessment(
        status=status,
        independent_runs=len(normalized_runs),
        independent_repositories=len(normalized_repositories),
        run_ids=normalized_runs,
        repositories=normalized_repositories,
    )
