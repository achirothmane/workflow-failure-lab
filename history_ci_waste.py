from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass

from ci_retry_gate import (
    FAILURE_CONCLUSIONS,
    TRANSIENT_CATEGORIES,
    GitHubAPI,
    classify_log,
    job_duration_minutes,
)


@dataclass(frozen=True)
class HistoricalFailure:
    run_id: int
    job_name: str
    category: str
    confidence: str
    duration_minutes: float


@dataclass(frozen=True)
class RecurringFailure:
    job_name: str
    category: str
    occurrences: int
    failed_minutes: float


@dataclass(frozen=True)
class HistorySummary:
    runs_analyzed: int
    failure_records: int
    failed_minutes: float
    transient_waste_minutes: float
    recurring: tuple[RecurringFailure, ...]


def summarize_history(
    failures: list[HistoricalFailure], *, runs_analyzed: int
) -> HistorySummary:
    failed_minutes = round(sum(item.duration_minutes for item in failures), 2)
    transient_waste_minutes = round(
        sum(
            item.duration_minutes
            for item in failures
            if item.category in TRANSIENT_CATEGORIES and item.confidence == "high"
        ),
        2,
    )

    counts: Counter[tuple[str, str]] = Counter()
    minutes: defaultdict[tuple[str, str], float] = defaultdict(float)
    for item in failures:
        key = (item.job_name, item.category)
        counts[key] += 1
        minutes[key] += item.duration_minutes

    recurring = [
        RecurringFailure(
            job_name=job_name,
            category=category,
            occurrences=count,
            failed_minutes=round(minutes[(job_name, category)], 2),
        )
        for (job_name, category), count in counts.items()
        if count >= 2
    ]
    recurring.sort(
        key=lambda item: (-item.occurrences, -item.failed_minutes, item.job_name, item.category)
    )

    return HistorySummary(
        runs_analyzed=runs_analyzed,
        failure_records=len(failures),
        failed_minutes=failed_minutes,
        transient_waste_minutes=transient_waste_minutes,
        recurring=tuple(recurring),
    )


def render_history_report(summary: HistorySummary) -> str:
    lines = [
        "## CI History & Waste",
        "",
        f"Historical runs analyzed: **{summary.runs_analyzed}**",
        f"Failed jobs observed: **{summary.failure_records}**",
        f"Historical failed-job runtime: **{summary.failed_minutes:.2f} min**",
        f"High-confidence transient CI waste: **{summary.transient_waste_minutes:.2f} min**",
        "",
    ]

    if summary.recurring:
        lines.extend(
            [
                "### Recurring failures",
                "",
                "| Job | Category | Occurrences | Failed runtime |",
                "|---|---|---:|---:|",
            ]
        )
        for item in summary.recurring[:10]:
            lines.append(
                f"| {item.job_name.replace('|', '/')} | `{item.category}` | "
                f"{item.occurrences} | {item.failed_minutes:.2f} min |"
            )
    else:
        lines.append("No recurring job/category failure pattern appeared at least twice in the sampled history.")

    lines.extend(
        [
            "",
            "> Failed-job runtime is not automatically waste. The transient-waste figure counts only jobs whose logs match a high-confidence runner/infrastructure or dependency/network signature.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def collect_history(
    api: GitHubAPI,
    repo: str,
    current_run: dict,
    history_runs: int,
) -> tuple[list[HistoricalFailure], int]:
    workflow_id = current_run.get("workflow_id")
    current_run_id = int(current_run.get("id") or 0)
    if not workflow_id or history_runs <= 0:
        return [], 0

    per_page = min(max(history_runs * 2, history_runs), 100)
    data = api.request(
        "GET",
        f"/repos/{repo}/actions/workflows/{workflow_id}/runs?status=completed&per_page={per_page}",
    )
    candidates = [
        run
        for run in (data.get("workflow_runs") or [])
        if int(run.get("id") or 0) != current_run_id
    ][:history_runs]

    failures: list[HistoricalFailure] = []
    for run in candidates:
        run_id = int(run.get("id") or 0)
        try:
            jobs = api.get_jobs(repo, run_id)
        except RuntimeError:
            continue

        for job in jobs:
            conclusion = str(job.get("conclusion") or "").lower()
            if conclusion not in FAILURE_CONCLUSIONS:
                continue

            job_id = int(job.get("id") or 0)
            try:
                log_text = api.get_job_logs(repo, job_id)
            except RuntimeError:
                log_text = ""

            classification = classify_log(log_text)
            failures.append(
                HistoricalFailure(
                    run_id=run_id,
                    job_name=str(job.get("name") or f"job-{job_id}"),
                    category=classification.category,
                    confidence=classification.confidence,
                    duration_minutes=job_duration_minutes(job),
                )
            )

    return failures, len(candidates)


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    run_id_raw = os.environ.get("INPUT_RUN_ID") or os.environ.get("GITHUB_RUN_ID")

    if not token or not repo or not run_id_raw:
        print("::warning::History analysis skipped because token, repository, or run ID is missing.")
        return 0

    try:
        run_id = int(run_id_raw)
        history_runs = max(0, min(int(os.environ.get("INPUT_HISTORY_RUNS", "10")), 50))
    except ValueError:
        print("::warning::History analysis skipped because run-id or history-runs is invalid.")
        return 0

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    try:
        current_run = api.get_run(repo, run_id)
        failures, runs_analyzed = collect_history(api, repo, current_run, history_runs)
    except RuntimeError as exc:
        print(f"::warning::History analysis unavailable: {exc}")
        return 0

    summary = summarize_history(failures, runs_analyzed=runs_analyzed)
    report = render_history_report(summary)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n" + report)
    else:
        print(report)

    _write_output("history-runs-analyzed", str(summary.runs_analyzed))
    _write_output("historical-failed-minutes", f"{summary.failed_minutes:.2f}")
    _write_output(
        "historical-transient-waste-minutes",
        f"{summary.transient_waste_minutes:.2f}",
    )
    _write_output("recurring-failures", str(len(summary.recurring)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
