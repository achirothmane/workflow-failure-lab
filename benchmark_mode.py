from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ci_retry_gate import (
    FAILURE_CONCLUSIONS,
    GitHubAPI,
    classify_log,
    detect_side_effect_risk,
    job_duration_minutes,
)
from history_ci_waste import (
    HistoricalFailure,
    _jobs_for_attempt,
    _later_rerun_outcome,
    failure_fingerprint,
)
from policy_shadow import simulate_shadow

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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


@dataclass(frozen=True)
class CategoryBenchmark:
    category: str
    failed_jobs: int
    decisions: int
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
    repositories: tuple[RepositoryBenchmark, ...]
    categories: tuple[CategoryBenchmark, ...]
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


def collect_repository_history(
    api: GitHubAPI,
    repo: str,
    run_limit: int,
) -> tuple[list[HistoricalFailure], int]:
    if run_limit <= 0:
        return [], 0

    per_page = min(max(run_limit, 1), 100)
    data = api.request(
        "GET",
        f"/repos/{repo}/actions/runs?status=completed&per_page={per_page}",
    )
    runs = list(data.get("workflow_runs") or [])[:run_limit]
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

        for job in attempt_jobs.get(1, []):
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
            fingerprint, signature = failure_fingerprint(
                job_name,
                classification.category,
                classification.evidence,
            )
            side_effect_risk, _ = detect_side_effect_risk(job)
            rerun_observed, recovered = _later_rerun_outcome(
                attempt_jobs,
                1,
                attempts,
                job_name,
                str(job.get("started_at") or ""),
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
                    side_effect_risk=side_effect_risk,
                    attempt=1,
                )
            )

    return failures, len(runs)


def summarize_benchmark(
    histories: dict[str, tuple[list[HistoricalFailure], int]],
    *,
    repositories_requested: int | None = None,
    skipped: tuple[tuple[str, str], ...] = (),
) -> BenchmarkSummary:
    repo_rows: list[RepositoryBenchmark] = []
    category_failures: Counter[str] = Counter()
    category_decisions: Counter[str] = Counter()
    category_evaluated: Counter[str] = Counter()
    category_recoveries: Counter[str] = Counter()
    category_false_positives: Counter[str] = Counter()
    category_unknown: Counter[str] = Counter()

    total_runs = 0
    total_failures = 0
    total_decisions = 0
    total_evaluated = 0
    total_recoveries = 0
    total_false_positives = 0
    total_unknown = 0

    for repo, (failures, runs_analyzed) in histories.items():
        # Policy learning remains repository-local. Evidence from repository A must
        # never promote a fingerprint in repository B.
        shadow = simulate_shadow(failures)
        first_attempt_failures = [item for item in failures if item.attempt == 1]
        for item in first_attempt_failures:
            category_failures[item.category] += 1
        for item in shadow.fingerprints:
            category_decisions[item.category] += item.decisions
            category_evaluated[item.category] += item.evaluated
            category_recoveries[item.category] += item.recoveries
            category_false_positives[item.category] += item.false_positives
            category_unknown[item.category] += item.unknown_outcomes

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
            )
        )
        total_runs += runs_analyzed
        total_failures += len(first_attempt_failures)
        total_decisions += shadow.decisions
        total_evaluated += shadow.evaluated
        total_recoveries += shadow.recoveries
        total_false_positives += shadow.false_positives
        total_unknown += shadow.unknown_outcomes

    repo_rows.sort(key=lambda item: (-item.evaluated, -item.decisions, item.repository))

    categories = []
    all_categories = sorted(set(category_failures) | set(category_decisions))
    for category in all_categories:
        categories.append(
            CategoryBenchmark(
                category=category,
                failed_jobs=category_failures[category],
                decisions=category_decisions[category],
                evaluated=category_evaluated[category],
                recoveries=category_recoveries[category],
                false_positives=category_false_positives[category],
                unknown_outcomes=category_unknown[category],
            )
        )
    categories.sort(key=lambda item: (-item.evaluated, -item.failed_jobs, item.category))

    requested = repositories_requested
    if requested is None:
        requested = len(histories) + len(skipped)

    return BenchmarkSummary(
        repositories_requested=requested,
        repositories_analyzed=len(histories),
        repositories_skipped=len(skipped),
        runs_analyzed=total_runs,
        failed_jobs=total_failures,
        decisions=total_decisions,
        evaluated=total_evaluated,
        recoveries=total_recoveries,
        false_positives=total_false_positives,
        unknown_outcomes=total_unknown,
        repositories=tuple(repo_rows),
        categories=tuple(categories),
        skipped=skipped,
    )


def render_benchmark_report(summary: BenchmarkSummary) -> str:
    lines = [
        "## CI Retry Gate Benchmark Mode",
        "",
        "> Read-only cross-repository backtest. Learned policy is isolated per repository; no rerun is triggered.",
        "",
        f"Repositories requested: **{summary.repositories_requested}**",
        f"Repositories analyzed: **{summary.repositories_analyzed}**",
        f"Repositories skipped: **{summary.repositories_skipped}**",
        f"Completed workflow runs sampled: **{summary.runs_analyzed}**",
        f"First-attempt failed jobs observed: **{summary.failed_jobs}**",
        f"Shadow AUTO_RERUN_ONCE decisions: **{summary.decisions}**",
        f"Decisions with observed rerun outcomes: **{summary.evaluated}**",
        f"Observed recoveries: **{summary.recoveries}**",
        f"Observed false positives: **{summary.false_positives}**",
        f"Unknown outcomes: **{summary.unknown_outcomes}**",
        f"Observed precision on evaluated decisions: **{summary.observed_precision:.1%}**",
        f"Decision coverage over failed jobs: **{summary.decision_coverage:.1%}**",
        f"Evaluated coverage over failed jobs: **{summary.evaluated_coverage:.1%}**",
        "",
    ]

    if summary.categories:
        lines.extend(
            [
                "### By failure category",
                "",
                "| Category | Failed jobs | Decisions | Evaluated | Recoveries | False positives | Unknown | Precision |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.categories:
            lines.append(
                f"| `{item.category}` | {item.failed_jobs} | {item.decisions} | {item.evaluated} | "
                f"{item.recoveries} | {item.false_positives} | {item.unknown_outcomes} | "
                f"{item.observed_precision:.1%} |"
            )

    if summary.repositories:
        lines.extend(
            [
                "",
                "### By repository",
                "",
                "| Repository | Runs | Failed jobs | Decisions | Evaluated | Recoveries | False positives | Precision |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.repositories[:20]:
            lines.append(
                f"| `{item.repository}` | {item.runs_analyzed} | {item.failed_jobs} | {item.decisions} | "
                f"{item.evaluated} | {item.recoveries} | {item.false_positives} | "
                f"{item.observed_precision:.1%} |"
            )

    if summary.skipped:
        lines.extend(["", "### Skipped repositories", ""])
        for repo, reason in summary.skipped[:20]:
            lines.append(f"- `{repo}` — {reason.replace('|', '/')}" )

    lines.extend(
        [
            "",
            "> Precision is recoveries / evaluated shadow decisions. It is not overall classifier accuracy. UNKNOWN outcomes are excluded from precision rather than guessed.",
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
    fallback_repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or ""
    raw_repos = os.environ.get("INPUT_BENCHMARK_REPOSITORIES", "")

    if not token:
        print("::warning::Benchmark skipped because github-token is missing.")
        return 0

    try:
        repositories = parse_repositories(raw_repos, fallback_repo)
        run_limit = max(1, min(int(os.environ.get("INPUT_BENCHMARK_RUNS", "20")), 50))
    except ValueError as exc:
        print(f"::error::Benchmark configuration invalid: {exc}")
        return 2

    if not repositories:
        print("::warning::Benchmark skipped because no repositories were provided.")
        return 0

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    histories: dict[str, tuple[list[HistoricalFailure], int]] = {}
    skipped: list[tuple[str, str]] = []

    for repo in repositories:
        try:
            histories[repo] = collect_repository_history(api, repo, run_limit)
        except RuntimeError as exc:
            skipped.append((repo, str(exc)[:240]))

    summary = summarize_benchmark(
        histories,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
