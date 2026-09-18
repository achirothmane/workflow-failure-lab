from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass

from ci_retry_gate import (
    AMBIGUOUS,
    CAUSAL,
    FAILURE_CONCLUSIONS,
    PROVENANCE_CONFIRMED,
    TRANSIENT_CATEGORIES,
    GitHubAPI,
    assess_execution_provenance,
    causal_evidence_role,
    classify_log,
    detect_side_effect_risk,
    job_duration_minutes,
)
from history_ci_waste import (
    HistoricalFailure,
    _jobs_for_attempt,
    failure_fingerprint,
)
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    RECOVERY_VALIDATED,
    assess_recovery_ground_truth,
    is_ground_truth_evaluable,
    is_validated_recovery,
    later_rerun_result,
)
from coverage_attribution import (
    GATE_CAUSAL_EVIDENCE,
    GATE_CLASSIFICATION_UNKNOWN,
    GATE_CODE_REGRESSION,
    GATE_ELIGIBLE,
    GATE_LOW_CONFIDENCE,
    GATE_NON_TRANSIENT_CATEGORY,
    GATE_PROVENANCE,
    GATE_SIDE_EFFECT,
    CoverageGateSummary,
    coverage_gate_count,
    evidence_gap_count,
    summarize_coverage_attribution,
)
from policy_shadow import simulate_shadow
from unknown_cause_decomposition import decompose_unknown_cause
from unknown_failure_intelligence import (
    UnknownIntelligenceSummary,
    summarize_unknown_patterns,
    unknown_signature,
)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

REJECTION_SIDE_EFFECT = "SIDE_EFFECT_RISK"
REJECTION_CODE_REGRESSION = "CODE_REGRESSION"
REJECTION_LOW_CONFIDENCE_TRANSIENT = "LOW_CONFIDENCE_TRANSIENT"
REJECTION_UNCONFIRMED_PROVENANCE = "UNCONFIRMED_EXECUTION_PROVENANCE"
REJECTION_UNKNOWN = "UNKNOWN_CLASSIFICATION"
REJECTION_NON_TRANSIENT = "NON_TRANSIENT_CATEGORY"


@dataclass(frozen=True)
class RepositoryBenchmark:
    repository: str
    runs_analyzed: int
    failed_jobs: int
    decisions: int
    evaluated: int
    recoveries: int
    false_positives: int
    unknown_outcomes: int
    rerun_runs_analyzed: int = 0
    rerun_failed_jobs: int = 0
    rerun_candidates: int = 0
    rerun_evaluated: int = 0
    rerun_recoveries: int = 0
    rerun_false_positives: int = 0
    rerun_unknown_outcomes: int = 0

    @property
    def observed_precision(self) -> float:
        if self.evaluated <= 0:
            return 0.0
        return self.recoveries / self.evaluated

    @property
    def decision_coverage(self) -> float:
        if self.failed_jobs <= 0:
            return 0.0
        return self.decisions / self.failed_jobs

    @property
    def rerun_observed_precision(self) -> float:
        if self.rerun_evaluated <= 0:
            return 0.0
        return self.rerun_recoveries / self.rerun_evaluated


@dataclass(frozen=True)
class CategoryBenchmark:
    category: str
    failed_jobs: int
    candidates: int
    evaluated: int
    recoveries: int
    false_positives: int
    unknown_outcomes: int

    @property
    def observed_precision(self) -> float:
        if self.evaluated <= 0:
            return 0.0
        return self.recoveries / self.evaluated


@dataclass(frozen=True)
class RejectionBenchmark:
    reason: str
    blocked: int
    recovered: int
    failed_again: int
    unknown_outcomes: int

    @property
    def observed_recovery_rate(self) -> float:
        evaluated = self.recovered + self.failed_again
        if evaluated <= 0:
            return 0.0
        return self.recovered / evaluated


@dataclass(frozen=True)
class BenchmarkSummary:
    repositories_requested: int
    repositories_analyzed: int
    repositories_skipped: int
    runs_analyzed: int
    failed_jobs: int
    decisions: int
    evaluated: int
    recoveries: int
    false_positives: int
    unknown_outcomes: int
    rerun_runs_analyzed: int
    rerun_failed_jobs: int
    rerun_candidates: int
    rerun_evaluated: int
    rerun_recoveries: int
    rerun_false_positives: int
    rerun_unknown_outcomes: int
    rerun_blocked: int
    rerun_blocked_recovered: int
    rerun_blocked_failed_again: int
    rerun_blocked_unknown: int
    repositories: tuple[RepositoryBenchmark, ...]
    categories: tuple[CategoryBenchmark, ...]
    rejections: tuple[RejectionBenchmark, ...]
    coverage_attribution: tuple[CoverageGateSummary, ...]
    unknown_intelligence: UnknownIntelligenceSummary
    skipped: tuple[tuple[str, str], ...]

    @property
    def observed_precision(self) -> float:
        if self.evaluated <= 0:
            return 0.0
        return self.recoveries / self.evaluated

    @property
    def decision_coverage(self) -> float:
        if self.failed_jobs <= 0:
            return 0.0
        return self.decisions / self.failed_jobs

    @property
    def evaluated_coverage(self) -> float:
        if self.failed_jobs <= 0:
            return 0.0
        return self.evaluated / self.failed_jobs

    @property
    def rerun_observed_precision(self) -> float:
        if self.rerun_evaluated <= 0:
            return 0.0
        return self.rerun_recoveries / self.rerun_evaluated

    @property
    def rerun_candidate_coverage(self) -> float:
        if self.rerun_failed_jobs <= 0:
            return 0.0
        return self.rerun_candidates / self.rerun_failed_jobs


def parse_repositories(raw: str, fallback: str = "") -> list[str]:
    source = raw.strip() or fallback.strip()
    if not source:
        return []

    items: list[str] = []
    seen: set[str] = set()
    for value in re.split(r"[\s,]+", source):
        repo = value.strip()
        if not repo:
            continue
        if not _REPO_RE.fullmatch(repo):
            raise ValueError(f"Invalid repository name: {repo!r}; expected owner/name")
        if repo not in seen:
            items.append(repo)
            seen.add(repo)
        if len(items) >= 50:
            break
    return items


def _list_completed_runs(api: GitHubAPI, repo: str, limit: int) -> list[dict]:
    if limit <= 0:
        return []

    limit = min(limit, 500)
    runs: list[dict] = []
    seen_run_ids: set[int] = set()
    page = 1
    while len(runs) < limit:
        per_page = min(100, limit - len(runs))
        data = api.request(
            "GET",
            f"/repos/{repo}/actions/runs?status=completed&per_page={per_page}&page={page}",
        )
        batch = list(data.get("workflow_runs") or [])
        if not batch:
            break

        for run in batch:
            run_id = int(run.get("id") or 0)
            if run_id > 0:
                if run_id in seen_run_ids:
                    continue
                seen_run_ids.add(run_id)
            runs.append(run)
            if len(runs) >= limit:
                break

        if len(batch) < per_page:
            break
        page += 1
    return runs[:limit]


def _collect_failures_for_runs(
    api: GitHubAPI,
    repo: str,
    runs: list[dict],
) -> list[HistoricalFailure]:
    failures: list[HistoricalFailure] = []

    for run in runs:
        run_id = int(run.get("id") or 0)
        if run_id <= 0:
            continue

        attempts = max(1, int(run.get("run_attempt") or 1))
        attempt_jobs: dict[int, list[dict]] = {}
        for attempt in range(1, attempts + 1):
            try:
                attempt_jobs[attempt] = _jobs_for_attempt(api, repo, run_id, attempt)
            except RuntimeError:
                if attempt == attempts:
                    try:
                        attempt_jobs[attempt] = api.get_jobs(repo, run_id)
                    except RuntimeError:
                        attempt_jobs[attempt] = []
                else:
                    attempt_jobs[attempt] = []

        first_attempt_jobs = attempt_jobs.get(1, [])
        workflow_side_effect_risk = any(
            detect_side_effect_risk(job)[0] for job in first_attempt_jobs
        )

        for job in first_attempt_jobs:
            conclusion = str(job.get("conclusion") or "").lower()
            if conclusion not in FAILURE_CONCLUSIONS:
                continue

            job_id = int(job.get("id") or 0)
            job_name = str(job.get("name") or f"job-{job_id}")
            try:
                log_text = api.get_job_logs(repo, job_id)
            except RuntimeError:
                log_text = ""

            classification = classify_log(log_text)
            causal_evidence_count = sum(
                causal_evidence_role(line) == CAUSAL
                for line in classification.evidence
            )
            ambiguous_evidence_count = sum(
                causal_evidence_role(line) == AMBIGUOUS
                for line in classification.evidence
            )
            provenance = assess_execution_provenance(job, log_text, classification)
            unknown_cause = ""
            unknown_cause_evidence: tuple[str, ...] = ()
            if classification.category == "UNKNOWN":
                signature = unknown_signature(log_text)
                cause = decompose_unknown_cause(log_text)
                unknown_cause = cause.cause
                unknown_cause_evidence = cause.matched_evidence or cause.evidence
                unknown_evidence = (
                    tuple() if signature == "unknown without stable evidence" else (signature,)
                )
                fingerprint, _ = failure_fingerprint(
                    job_name,
                    classification.category,
                    unknown_evidence,
                )
            else:
                fingerprint, signature = failure_fingerprint(
                    job_name,
                    classification.category,
                    classification.evidence,
                )
            own_side_effect_risk, _ = detect_side_effect_risk(job)
            rerun_observed, recovered, rerun_job = later_rerun_result(
                attempt_jobs,
                1,
                attempts,
                job_name,
                str(job.get("started_at") or ""),
            )
            recovery = assess_recovery_ground_truth(
                original_job=job,
                provenance_status=provenance.status,
                provenance_step=provenance.step_name,
                rerun_observed=rerun_observed,
                recovered=recovered,
                rerun_job=rerun_job,
            )
            failures.append(
                HistoricalFailure(
                    run_id=run_id,
                    job_name=job_name,
                    category=classification.category,
                    confidence=classification.confidence,
                    duration_minutes=job_duration_minutes(job),
                    fingerprint=fingerprint,
                    signature=signature,
                    recovered_after_rerun=recovered,
                    rerun_observed=rerun_observed,
                    side_effect_risk=(
                        own_side_effect_risk or workflow_side_effect_risk
                    ),
                    attempt=1,
                    provenance_status=provenance.status,
                    recovery_status=recovery.status,
                    recovery_evidence=recovery.evidence,
                    causal_evidence_count=causal_evidence_count,
                    ambiguous_evidence_count=ambiguous_evidence_count,
                    unknown_cause=unknown_cause,
                    unknown_cause_evidence=unknown_cause_evidence,
                )
            )

    return failures


def collect_repository_history(
    api: GitHubAPI,
    repo: str,
    run_limit: int,
) -> tuple[list[HistoricalFailure], int]:
    """Backward-compatible natural sample collector."""
    runs = _list_completed_runs(api, repo, run_limit)
    return _collect_failures_for_runs(api, repo, runs), len(runs)


def collect_repository_samples(
    api: GitHubAPI,
    repo: str,
    natural_run_limit: int,
    rerun_run_limit: int,
    rerun_search_limit: int,
) -> tuple[
    tuple[list[HistoricalFailure], int],
    tuple[list[HistoricalFailure], int],
]:
    """Collect separate natural and rerun-enriched benchmark samples.

    The natural sample is the latest N completed runs and measures real-world
    coverage. The enriched sample searches a larger history window for runs
    whose run_attempt > 1 and excludes natural-sample run IDs so precision
    evidence is not mixed into the coverage sample.
    """
    search_limit = max(natural_run_limit, rerun_search_limit)
    runs = _list_completed_runs(api, repo, search_limit)

    natural_runs = runs[:natural_run_limit]
    natural_ids = {int(run.get("id") or 0) for run in natural_runs}
    rerun_runs = [
        run
        for run in runs
        if int(run.get("run_attempt") or 1) > 1
        and int(run.get("id") or 0) not in natural_ids
    ][:rerun_run_limit]

    natural_failures = _collect_failures_for_runs(api, repo, natural_runs)
    rerun_failures = _collect_failures_for_runs(api, repo, rerun_runs)
    return (
        (natural_failures, len(natural_runs)),
        (rerun_failures, len(rerun_runs)),
    )


def _is_rerun_candidate(item: HistoricalFailure) -> bool:
    return (
        item.category in TRANSIENT_CATEGORIES
        and item.confidence == "high"
        and item.provenance_status == PROVENANCE_CONFIRMED
        and not item.side_effect_risk
    )


def _rejection_reason(item: HistoricalFailure) -> str | None:
    if _is_rerun_candidate(item):
        return None
    if item.side_effect_risk:
        return REJECTION_SIDE_EFFECT
    if item.category == "CODE_REGRESSION":
        return REJECTION_CODE_REGRESSION
    if item.category in TRANSIENT_CATEGORIES and item.confidence != "high":
        return REJECTION_LOW_CONFIDENCE_TRANSIENT
    if (
        item.category in TRANSIENT_CATEGORIES
        and item.confidence == "high"
        and item.provenance_status != PROVENANCE_CONFIRMED
    ):
        return REJECTION_UNCONFIRMED_PROVENANCE
    if item.category == "UNKNOWN":
        return REJECTION_UNKNOWN
    return REJECTION_NON_TRANSIENT


def _rerun_validation(
    failures: list[HistoricalFailure],
) -> tuple[int, int, int, int, int]:
    candidates = [item for item in failures if _is_rerun_candidate(item)]
    recoveries = sum(
        is_validated_recovery(item.recovery_status) for item in candidates
    )
    false_positives = sum(
        item.recovery_status == RECOVERY_NOT_RECOVERED for item in candidates
    )
    unknown = sum(
        not is_ground_truth_evaluable(item.recovery_status) for item in candidates
    )
    evaluated = recoveries + false_positives
    return len(candidates), evaluated, recoveries, false_positives, unknown


def summarize_benchmark(
    histories: dict[str, tuple[list[HistoricalFailure], int]],
    *,
    rerun_histories: dict[str, tuple[list[HistoricalFailure], int]] | None = None,
    repositories_requested: int | None = None,
    skipped: tuple[tuple[str, str], ...] = (),
) -> BenchmarkSummary:
    rerun_histories = rerun_histories or {}

    repo_rows: list[RepositoryBenchmark] = []
    category_failed: Counter[str] = Counter()
    category_candidates: Counter[str] = Counter()
    category_evaluated: Counter[str] = Counter()
    category_recoveries: Counter[str] = Counter()
    category_false_positives: Counter[str] = Counter()
    category_unknown: Counter[str] = Counter()
    rejection_blocked: Counter[str] = Counter()
    rejection_recovered: Counter[str] = Counter()
    rejection_failed_again: Counter[str] = Counter()
    rejection_unknown: Counter[str] = Counter()

    total_runs = 0
    total_failures = 0
    total_decisions = 0
    total_evaluated = 0
    total_recoveries = 0
    total_false_positives = 0
    total_unknown = 0

    total_rerun_runs = 0
    total_rerun_failures = 0
    total_rerun_candidates = 0
    total_rerun_evaluated = 0
    total_rerun_recoveries = 0
    total_rerun_false_positives = 0
    total_rerun_unknown = 0

    repositories = sorted(set(histories) | set(rerun_histories))
    for repo in repositories:
        failures, runs_analyzed = histories.get(repo, ([], 0))
        rerun_failures, rerun_runs_analyzed = rerun_histories.get(repo, ([], 0))

        shadow = simulate_shadow(failures)
        first_attempt_failures = [item for item in failures if item.attempt == 1]

        (
            rerun_candidates,
            rerun_evaluated,
            rerun_recoveries,
            rerun_false_positives,
            rerun_unknown,
        ) = _rerun_validation(rerun_failures)

        for item in rerun_failures:
            category_failed[item.category] += 1
            if _is_rerun_candidate(item):
                category_candidates[item.category] += 1
                if is_validated_recovery(item.recovery_status):
                    category_evaluated[item.category] += 1
                    category_recoveries[item.category] += 1
                elif item.recovery_status == RECOVERY_NOT_RECOVERED:
                    category_evaluated[item.category] += 1
                    category_false_positives[item.category] += 1
                else:
                    category_unknown[item.category] += 1
            else:
                reason = _rejection_reason(item)
                if reason is None:
                    continue
                rejection_blocked[reason] += 1
                if is_validated_recovery(item.recovery_status):
                    rejection_recovered[reason] += 1
                elif item.recovery_status == RECOVERY_NOT_RECOVERED:
                    rejection_failed_again[reason] += 1
                else:
                    rejection_unknown[reason] += 1

        repo_rows.append(
            RepositoryBenchmark(
                repository=repo,
                runs_analyzed=runs_analyzed,
                failed_jobs=len(first_attempt_failures),
                decisions=shadow.decisions,
                evaluated=shadow.evaluated,
                recoveries=shadow.recoveries,
                false_positives=shadow.false_positives,
                unknown_outcomes=shadow.unknown_outcomes,
                rerun_runs_analyzed=rerun_runs_analyzed,
                rerun_failed_jobs=len(rerun_failures),
                rerun_candidates=rerun_candidates,
                rerun_evaluated=rerun_evaluated,
                rerun_recoveries=rerun_recoveries,
                rerun_false_positives=rerun_false_positives,
                rerun_unknown_outcomes=rerun_unknown,
            )
        )

        total_runs += runs_analyzed
        total_failures += len(first_attempt_failures)
        total_decisions += shadow.decisions
        total_evaluated += shadow.evaluated
        total_recoveries += shadow.recoveries
        total_false_positives += shadow.false_positives
        total_unknown += shadow.unknown_outcomes

        total_rerun_runs += rerun_runs_analyzed
        total_rerun_failures += len(rerun_failures)
        total_rerun_candidates += rerun_candidates
        total_rerun_evaluated += rerun_evaluated
        total_rerun_recoveries += rerun_recoveries
        total_rerun_false_positives += rerun_false_positives
        total_rerun_unknown += rerun_unknown

    repo_rows.sort(
        key=lambda item: (
            -item.rerun_evaluated,
            -item.rerun_candidates,
            -item.evaluated,
            item.repository,
        )
    )

    categories: list[CategoryBenchmark] = []
    for category in sorted(category_failed):
        categories.append(
            CategoryBenchmark(
                category=category,
                failed_jobs=category_failed[category],
                candidates=category_candidates[category],
                evaluated=category_evaluated[category],
                recoveries=category_recoveries[category],
                false_positives=category_false_positives[category],
                unknown_outcomes=category_unknown[category],
            )
        )
    categories.sort(
        key=lambda item: (-item.evaluated, -item.candidates, -item.failed_jobs, item.category)
    )

    rejections = [
        RejectionBenchmark(
            reason=reason,
            blocked=rejection_blocked[reason],
            recovered=rejection_recovered[reason],
            failed_again=rejection_failed_again[reason],
            unknown_outcomes=rejection_unknown[reason],
        )
        for reason in sorted(rejection_blocked)
    ]
    rejections.sort(key=lambda item: (-item.blocked, item.reason))

    total_rerun_blocked = sum(item.blocked for item in rejections)
    total_rerun_blocked_recovered = sum(item.recovered for item in rejections)
    total_rerun_blocked_failed_again = sum(item.failed_again for item in rejections)
    total_rerun_blocked_unknown = sum(item.unknown_outcomes for item in rejections)

    all_rerun_failures = [
        item
        for failures, _runs in rerun_histories.values()
        for item in failures
    ]
    coverage_attribution = summarize_coverage_attribution(all_rerun_failures)
    unknown_intelligence = summarize_unknown_patterns(histories, rerun_histories)

    requested = repositories_requested
    if requested is None:
        requested = len(repositories) + len(skipped)

    return BenchmarkSummary(
        repositories_requested=requested,
        repositories_analyzed=len(repositories),
        repositories_skipped=len(skipped),
        runs_analyzed=total_runs,
        failed_jobs=total_failures,
        decisions=total_decisions,
        evaluated=total_evaluated,
        recoveries=total_recoveries,
        false_positives=total_false_positives,
        unknown_outcomes=total_unknown,
        rerun_runs_analyzed=total_rerun_runs,
        rerun_failed_jobs=total_rerun_failures,
        rerun_candidates=total_rerun_candidates,
        rerun_evaluated=total_rerun_evaluated,
        rerun_recoveries=total_rerun_recoveries,
        rerun_false_positives=total_rerun_false_positives,
        rerun_unknown_outcomes=total_rerun_unknown,
        rerun_blocked=total_rerun_blocked,
        rerun_blocked_recovered=total_rerun_blocked_recovered,
        rerun_blocked_failed_again=total_rerun_blocked_failed_again,
        rerun_blocked_unknown=total_rerun_blocked_unknown,
        repositories=tuple(repo_rows),
        categories=tuple(categories),
        rejections=tuple(rejections),
        coverage_attribution=coverage_attribution,
        unknown_intelligence=unknown_intelligence,
        skipped=skipped,
    )


def render_benchmark_report(summary: BenchmarkSummary) -> str:
    lines = [
        "## CI Retry Gate Benchmark Mode",
        "",
        "> Read-only cross-repository backtest. Evidence stays isolated per repository; no rerun is triggered.",
        "",
        f"Repositories requested: **{summary.repositories_requested}**",
        f"Repositories analyzed: **{summary.repositories_analyzed}**",
        f"Repositories skipped: **{summary.repositories_skipped}**",
        "",
        "### Natural sample — coverage",
        "",
        f"Recent completed workflow runs sampled: **{summary.runs_analyzed}**",
        f"First-attempt failed jobs observed: **{summary.failed_jobs}**",
        f"Learned-policy shadow AUTO_RERUN_ONCE decisions: **{summary.decisions}**",
        f"Policy decisions with observed rerun outcomes: **{summary.evaluated}**",
        f"Natural-sample decision coverage: **{summary.decision_coverage:.1%}**",
        "",
        "### Rerun-enriched sample — precision",
        "",
        f"Historical rerun runs sampled: **{summary.rerun_runs_analyzed}**",
        f"First-attempt failed jobs in rerun runs: **{summary.rerun_failed_jobs}**",
        f"Base safety candidates (high-confidence transient, confirmed execution provenance, no side effects): **{summary.rerun_candidates}**",
        f"Candidates with ground-truth-evaluable rerun outcomes: **{summary.rerun_evaluated}**",
        f"Validated recoveries: **{summary.rerun_recoveries}**",
        f"Observed failed reruns: **{summary.rerun_false_positives}**",
        f"Unknown or unverified candidate outcomes: **{summary.rerun_unknown_outcomes}**",
        f"Ground-truth candidate precision: **{summary.rerun_observed_precision:.1%}**",
        f"Candidate coverage inside rerun-enriched failures: **{summary.rerun_candidate_coverage:.1%}**",
        "",
    ]

    if summary.coverage_attribution:
        lines.extend(
            [
                "### Coverage Attribution — first limiting layer",
                "",
                f"Failures stopped at evidence-gap layers: **{evidence_gap_count(summary.coverage_attribution)}**",
                "",
                "| First limiting layer | Type | Failures | Raw later successes | Validated recoveries | Failed reruns | Unknown / unverified |",
                "|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.coverage_attribution:
            lines.append(
                f"| `{item.gate}` | `{item.kind}` | {item.failures} | "
                f"{item.raw_later_successes} | {item.validated_recoveries} | "
                f"{item.failed_reruns} | {item.unknown_or_unverified} |"
            )
        lines.extend(
            [
                "",
                "> Coverage Attribution is diagnostic only. It records the first limiting layer in pipeline order; it does not bypass a later authority boundary or grant rerun permission.",
                "",
            ]
        )

    if summary.rejections:
        lines.extend(
            [
                "### Blocked / missed-recovery intelligence",
                "",
                f"Blocked non-candidates: **{summary.rerun_blocked}**",
                f"Blocked failures that later recovered after a real rerun: **{summary.rerun_blocked_recovered}**",
                f"Blocked failures that failed again after a real rerun: **{summary.rerun_blocked_failed_again}**",
                f"Blocked failures without an observable real rerun outcome: **{summary.rerun_blocked_unknown}**",
                "",
                "| Rejection reason | Blocked | Recovered later | Failed again | Unknown | Observed recovery rate |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.rejections:
            lines.append(
                f"| `{item.reason}` | {item.blocked} | {item.recovered} | "
                f"{item.failed_again} | {item.unknown_outcomes} | "
                f"{item.observed_recovery_rate:.1%} |"
            )
        lines.extend(
            [
                "",
                "> A blocked failure recovering after a rerun is a coverage signal, not proof that automatic rerun was safe. Side effects, code-regression evidence, low confidence, and unconfirmed execution provenance remain blocking evidence.",
                "",
            ]
        )

    if summary.unknown_intelligence.patterns:
        unknown = summary.unknown_intelligence
        lines.extend(
            [
                "### Unknown Failure Intelligence",
                "",
                f"UNKNOWN failures across natural + rerun-enriched samples: **{unknown.unknown_failures}**",
                f"Distinct UNKNOWN signatures: **{len(unknown.patterns)}**",
                f"Repeated UNKNOWN signatures: **{unknown.repeated_patterns}**",
                f"UNKNOWN cases with ground-truth-evaluable reruns: **{unknown.evaluated_reruns}**",
                f"Validated UNKNOWN recoveries: **{unknown.recoveries}**",
                f"Observed UNKNOWN failures after rerun: **{unknown.failed_again}**",
                f"Investigation candidates for a possible future transient classifier rule: **{len(unknown.promotion_candidates)}**",
                "",
                "| Pattern | Occurrences | Repositories | GT-evaluable reruns | Validated recoveries | Failed again | Recovery rate | Status | Signature |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        if unknown.causes:
            lines.extend(
                [
                    "",
                    "#### UNKNOWN Cause Decomposition",
                    "",
                    "| Cause family | Occurrences | Repositories | GT-evaluable reruns | Validated recoveries | Failed again | Unknown / unverified | Side-effect occurrences |",
                    "|---|---:|---:|---:|---:|---:|---:|---:|",
                ]
            )
            for cause in unknown.causes:
                lines.append(
                    f"| `{cause.cause}` | {cause.occurrences} | {cause.repositories} | "
                    f"{cause.rerun_observations} | {cause.recoveries} | {cause.failed_again} | "
                    f"{cause.unknown_outcomes} | {cause.side_effect_occurrences} |"
                )
            lines.extend(
                [
                    "",
                    "> Cause families are diagnostic buckets only. They do not modify UNKNOWN runtime classification or authorize reruns.",
                    "",
                ]
            )

        for item in unknown.patterns[:20]:
            safe_signature = item.signature.replace("|", "/")
            lines.append(
                f"| `{item.pattern_id}` | {item.occurrences} | {item.repositories} | "
                f"{item.rerun_observations} | {item.recoveries} | {item.failed_again} | "
                f"{item.recovery_rate:.1%} | `{item.status}` | {safe_signature} |"
            )
        lines.extend(
            [
                "",
                "> INVESTIGATE_TRANSIENT_PATTERN is advisory only. It requires a stable repeated signature, at least 3 ground-truth-evaluable reruns, at least 80% validated recovery, and no side-effect occurrence. It does not modify the runtime classifier or authorize reruns.",
                "",
            ]
        )

    if summary.categories:
        lines.extend(
            [
                "### Rerun-enriched results by failure category",
                "",
                "| Category | Failed jobs | Candidates | Evaluated | Recoveries | False positives | Unknown | Precision |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.categories:
            lines.append(
                f"| `{item.category}` | {item.failed_jobs} | {item.candidates} | "
                f"{item.evaluated} | {item.recoveries} | {item.false_positives} | "
                f"{item.unknown_outcomes} | {item.observed_precision:.1%} |"
            )

    if summary.repositories:
        lines.extend(
            [
                "",
                "### By repository",
                "",
                "| Repository | Natural runs | Natural failures | Natural policy decisions | Rerun runs | Rerun failures | Candidates | Evaluated | Recoveries | False positives | Candidate precision |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.repositories[:20]:
            lines.append(
                f"| `{item.repository}` | {item.runs_analyzed} | {item.failed_jobs} | "
                f"{item.decisions} | {item.rerun_runs_analyzed} | "
                f"{item.rerun_failed_jobs} | {item.rerun_candidates} | "
                f"{item.rerun_evaluated} | {item.rerun_recoveries} | "
                f"{item.rerun_false_positives} | {item.rerun_observed_precision:.1%} |"
            )

    if summary.skipped:
        lines.extend(["", "### Skipped repositories", ""])
        for repo, reason in summary.skipped[:20]:
            lines.append(f"- `{repo}` — {reason.replace('|', '/')}")

    lines.extend(
        [
            "",
            "> The natural sample measures how often the learned policy would act in ordinary recent CI history.",
            "> The rerun-enriched sample deliberately over-samples runs that were actually rerun, so its precision must not be interpreted as prevalence or natural coverage.",
            "> Candidate precision is validated recoveries / ground-truth-evaluable high-confidence transient candidates with confirmed failed-step provenance and no workflow side-effect signal. Later successes that cannot be tied back to the original failed step remain unknown rather than being credited as recoveries.",
            "> Benchmark results describe only the sampled repositories and historical runs. They are not a guarantee of future production behavior.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    fallback_repo = (
        os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or ""
    )
    raw_repos = os.environ.get("INPUT_BENCHMARK_REPOSITORIES", "")

    if not token:
        print("::warning::Benchmark skipped because github-token is missing.")
        return 0

    try:
        repositories = parse_repositories(raw_repos, fallback_repo)
        natural_run_limit = max(
            1, min(int(os.environ.get("INPUT_BENCHMARK_RUNS", "20")), 50)
        )
        rerun_run_limit = max(
            1, min(int(os.environ.get("INPUT_BENCHMARK_RERUN_RUNS", "20")), 50)
        )
        rerun_search_limit = max(
            natural_run_limit,
            min(
                int(os.environ.get("INPUT_BENCHMARK_RERUN_SEARCH_RUNS", "200")),
                500,
            ),
        )
    except ValueError as exc:
        print(f"::error::Benchmark configuration invalid: {exc}")
        return 2

    if not repositories:
        print("::warning::Benchmark skipped because no repositories were provided.")
        return 0

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    histories: dict[str, tuple[list[HistoricalFailure], int]] = {}
    rerun_histories: dict[str, tuple[list[HistoricalFailure], int]] = {}
    skipped: list[tuple[str, str]] = []

    for repo in repositories:
        try:
            natural, enriched = collect_repository_samples(
                api,
                repo,
                natural_run_limit,
                rerun_run_limit,
                rerun_search_limit,
            )
            histories[repo] = natural
            rerun_histories[repo] = enriched
        except RuntimeError as exc:
            skipped.append((repo, str(exc)[:240]))

    summary = summarize_benchmark(
        histories,
        rerun_histories=rerun_histories,
        repositories_requested=len(repositories),
        skipped=tuple(skipped),
    )
    report = render_benchmark_report(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n" + report)
    else:
        print(report)

    _write_output("benchmark-repositories-analyzed", str(summary.repositories_analyzed))
    _write_output("benchmark-repositories-skipped", str(summary.repositories_skipped))
    _write_output("benchmark-runs-analyzed", str(summary.runs_analyzed))
    _write_output("benchmark-failed-jobs", str(summary.failed_jobs))
    _write_output("benchmark-shadow-decisions", str(summary.decisions))
    _write_output("benchmark-evaluated-decisions", str(summary.evaluated))
    _write_output("benchmark-recoveries", str(summary.recoveries))
    _write_output("benchmark-false-positives", str(summary.false_positives))
    _write_output("benchmark-unknown-outcomes", str(summary.unknown_outcomes))
    _write_output("benchmark-observed-precision", f"{summary.observed_precision:.4f}")
    _write_output("benchmark-decision-coverage", f"{summary.decision_coverage:.4f}")
    _write_output("benchmark-evaluated-coverage", f"{summary.evaluated_coverage:.4f}")

    _write_output("benchmark-rerun-runs-analyzed", str(summary.rerun_runs_analyzed))
    _write_output("benchmark-rerun-failed-jobs", str(summary.rerun_failed_jobs))
    _write_output("benchmark-rerun-candidates", str(summary.rerun_candidates))
    _write_output("benchmark-rerun-evaluated", str(summary.rerun_evaluated))
    _write_output("benchmark-rerun-recoveries", str(summary.rerun_recoveries))
    _write_output(
        "benchmark-rerun-false-positives",
        str(summary.rerun_false_positives),
    )
    _write_output(
        "benchmark-rerun-unknown-outcomes",
        str(summary.rerun_unknown_outcomes),
    )
    _write_output(
        "benchmark-rerun-observed-precision",
        f"{summary.rerun_observed_precision:.4f}",
    )
    _write_output(
        "benchmark-rerun-candidate-coverage",
        f"{summary.rerun_candidate_coverage:.4f}",
    )
    _write_output("benchmark-rerun-blocked", str(summary.rerun_blocked))
    _write_output(
        "benchmark-rerun-blocked-recovered",
        str(summary.rerun_blocked_recovered),
    )
    _write_output(
        "benchmark-rerun-blocked-failed-again",
        str(summary.rerun_blocked_failed_again),
    )
    _write_output(
        "benchmark-rerun-blocked-unknown",
        str(summary.rerun_blocked_unknown),
    )
    _write_output(
        "benchmark-coverage-evidence-gaps",
        str(evidence_gap_count(summary.coverage_attribution)),
    )
    _write_output(
        "benchmark-coverage-classification-unknown",
        str(coverage_gate_count(summary.coverage_attribution, GATE_CLASSIFICATION_UNKNOWN)),
    )
    _write_output(
        "benchmark-coverage-non-transient",
        str(coverage_gate_count(summary.coverage_attribution, GATE_NON_TRANSIENT_CATEGORY)),
    )
    _write_output(
        "benchmark-coverage-code-regression",
        str(coverage_gate_count(summary.coverage_attribution, GATE_CODE_REGRESSION)),
    )
    _write_output(
        "benchmark-coverage-causal-evidence",
        str(coverage_gate_count(summary.coverage_attribution, GATE_CAUSAL_EVIDENCE)),
    )
    _write_output(
        "benchmark-coverage-low-confidence",
        str(coverage_gate_count(summary.coverage_attribution, GATE_LOW_CONFIDENCE)),
    )
    _write_output(
        "benchmark-coverage-unconfirmed-provenance",
        str(coverage_gate_count(summary.coverage_attribution, GATE_PROVENANCE)),
    )
    _write_output(
        "benchmark-coverage-side-effect-boundary",
        str(coverage_gate_count(summary.coverage_attribution, GATE_SIDE_EFFECT)),
    )
    _write_output(
        "benchmark-coverage-eligible",
        str(coverage_gate_count(summary.coverage_attribution, GATE_ELIGIBLE)),
    )
    _write_output(
        "benchmark-rejection-side-effect",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_SIDE_EFFECT), 0)),
    )
    _write_output(
        "benchmark-rejection-code-regression",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_CODE_REGRESSION), 0)),
    )
    _write_output(
        "benchmark-rejection-low-confidence-transient",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_LOW_CONFIDENCE_TRANSIENT), 0)),
    )
    _write_output(
        "benchmark-rejection-unconfirmed-provenance",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_UNCONFIRMED_PROVENANCE), 0)),
    )
    _write_output(
        "benchmark-rejection-unknown-classification",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_UNKNOWN), 0)),
    )
    _write_output(
        "benchmark-rejection-non-transient",
        str(next((item.blocked for item in summary.rejections if item.reason == REJECTION_NON_TRANSIENT), 0)),
    )
    _write_output(
        "benchmark-unknown-patterns",
        str(len(summary.unknown_intelligence.patterns)),
    )
    _write_output(
        "benchmark-unknown-repeated-patterns",
        str(summary.unknown_intelligence.repeated_patterns),
    )
    _write_output(
        "benchmark-unknown-evaluated-reruns",
        str(summary.unknown_intelligence.evaluated_reruns),
    )
    _write_output(
        "benchmark-unknown-recoveries",
        str(summary.unknown_intelligence.recoveries),
    )
    _write_output(
        "benchmark-unknown-failed-again",
        str(summary.unknown_intelligence.failed_again),
    )
    _write_output(
        "benchmark-unknown-promotion-candidates",
        str(len(summary.unknown_intelligence.promotion_candidates)),
    )
    _write_output(
        "benchmark-unknown-promotion-candidate-ids",
        ",".join(item.pattern_id for item in summary.unknown_intelligence.promotion_candidates),
    )
    unknown_causes = {
        item.cause: item.occurrences
        for item in summary.unknown_intelligence.causes
    }
    for cause_name in (
        "NO_STABLE_ERROR_EVIDENCE",
        "AUTH_PERMISSION",
        "GIT_VCS",
        "COMMAND_CONFIG",
        "TEST_BUILD",
        "PACKAGE_TOOL",
        "TOOL_ACTION_SPECIFIC",
        "AMBIGUOUS_OPERATIONAL",
    ):
        _write_output(
            "benchmark-unknown-cause-" + cause_name.lower().replace("_", "-"),
            str(unknown_causes.get(cause_name, 0)),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
