from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from ci_retry_gate import GitHubAPI, FAILURE_CONCLUSIONS
from flaky_test_history import _artifact_attempt, _xml_members
from flaky_test_intelligence import FAIL, PASS, observations_from_junit


DEFAULT_REPOSITORIES = (
    "huggingface/transformers",
    "denoland/deno",
    "DataDog/dd-trace-js",
    "databricks/dbt-databricks",
    "opencobra/cobratoolbox",
    "PostHog/posthog",
    "microsoft/playwright",
    "apache/airflow",
    "pandas-dev/pandas",
    "pytest-dev/pytest",
    "encode/httpx",
    "pallets/flask",
    "fastapi/fastapi",
    "pydantic/pydantic",
    "astral-sh/ruff",
    "getsentry/sentry",
    "grafana/grafana",
)

ARTIFACT_HINTS = (
    "junit",
    "test",
    "pytest",
    "jest",
    "vitest",
    "unit",
    "result",
    "report",
)

MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _list_runs(api: GitHubAPI, repo: str, limit: int) -> list[dict]:
    runs: list[dict] = []
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
        runs.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return runs[:limit]


def _attempt_windows(api: GitHubAPI, repo: str, run_id: int, attempts: int):
    windows = {}
    for attempt in range(1, attempts + 1):
        try:
            data = api.request(
                "GET",
                f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
            )
        except RuntimeError:
            continue
        jobs = list(data.get("jobs") or [])
        starts = [_dt(str(j.get("started_at") or "")) for j in jobs]
        ends = [_dt(str(j.get("completed_at") or "")) for j in jobs]
        starts = [x for x in starts if x is not None]
        ends = [x for x in ends if x is not None]
        if starts and ends:
            windows[attempt] = (min(starts), max(ends) + timedelta(minutes=15))
    return windows


def _bind_artifact_attempt(artifact: dict, run_attempt: int, windows: dict):
    name = str(artifact.get("name") or "")
    explicit = _artifact_attempt(name, run_attempt)
    if explicit is not None:
        return explicit, "NAME"

    created = _dt(str(artifact.get("created_at") or ""))
    if created is None:
        return None, "UNBOUND"

    matches = [
        attempt
        for attempt, (start, end) in windows.items()
        if start <= created <= end
    ]
    if len(matches) == 1:
        return matches[0], "TIME_WINDOW"
    return None, "UNBOUND"


def _artifact_looks_relevant(artifact: dict) -> bool:
    name = str(artifact.get("name") or "").lower()
    size = int(artifact.get("size_in_bytes") or 0)
    return (
        not bool(artifact.get("expired"))
        and 0 < size <= MAX_DOWNLOAD_BYTES
        and any(hint in name for hint in ARTIFACT_HINTS)
    )


def _same_sha_recoveries(observations):
    by_test = {}
    for item in observations:
        by_test.setdefault(item.test_id, []).append(item)

    recoveries = []
    for test_id, items in by_test.items():
        ordered = sorted(items, key=lambda x: (x.attempt, x.run_id))
        failures = [x for x in ordered if x.status == FAIL]
        passes = [x for x in ordered if x.status == PASS]
        for failure in failures:
            if any(
                p.sha == failure.sha
                and p.run_id == failure.run_id
                and p.attempt > failure.attempt
                for p in passes
            ):
                recoveries.append(test_id)
                break
    return sorted(set(recoveries))


def discover_repository(api: GitHubAPI, repo: str, run_limit: int):
    runs = _list_runs(api, repo, run_limit)
    reruns = [r for r in runs if int(r.get("run_attempt") or 1) > 1]

    result = {
        "repository": repo,
        "runs_scanned": len(runs),
        "rerun_runs": len(reruns),
        "runs_with_artifacts": 0,
        "runs_with_junit": 0,
        "runs_with_bound_junit": 0,
        "runs_with_same_sha_recovery": 0,
        "candidates": [],
    }

    for run in reruns:
        run_id = int(run.get("id") or 0)
        sha = str(run.get("head_sha") or "")
        attempts = int(run.get("run_attempt") or 1)
        windows = _attempt_windows(api, repo, run_id, attempts)

        data = api.request(
            "GET",
            f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
        )
        artifacts = list(data.get("artifacts") or [])
        if artifacts:
            result["runs_with_artifacts"] += 1

        observations = []
        junit_artifacts = 0
        bound_artifacts = 0
        artifact_rows = []

        for artifact in artifacts:
            if not _artifact_looks_relevant(artifact):
                continue
            artifact_id = int(artifact.get("id") or 0)
            if not artifact_id:
                continue
            attempt, binding = _bind_artifact_attempt(artifact, attempts, windows)
            try:
                blob = api.request_bytes(
                    "GET",
                    f"/repos/{repo}/actions/artifacts/{artifact_id}/zip",
                    accept="application/vnd.github+json",
                )
                members = _xml_members(blob)
            except (RuntimeError, ValueError):
                continue
            parsed = []
            for _, xml_text in members:
                try:
                    parsed.extend(
                        observations_from_junit(
                            xml_text,
                            sha=sha,
                            run_id=run_id,
                            attempt=attempt or 0,
                            job_name=str(artifact.get("name") or "artifact"),
                            observed_at=str(artifact.get("created_at") or ""),
                        )
                    )
                except ValueError:
                    continue
            if not parsed:
                continue

            junit_artifacts += 1
            if attempt is not None:
                bound_artifacts += 1
                observations.extend(parsed)
            artifact_rows.append(
                {
                    "name": str(artifact.get("name") or ""),
                    "attempt": attempt,
                    "binding": binding,
                    "observations": len(parsed),
                }
            )

        if junit_artifacts:
            result["runs_with_junit"] += 1
        if bound_artifacts:
            result["runs_with_bound_junit"] += 1

        recoveries = _same_sha_recoveries(observations)
        if recoveries:
            result["runs_with_same_sha_recovery"] += 1
            result["candidates"].append(
                {
                    "run_id": run_id,
                    "workflow": str(run.get("name") or ""),
                    "attempts": attempts,
                    "conclusion": str(run.get("conclusion") or ""),
                    "created_at": str(run.get("created_at") or ""),
                    "artifacts": artifact_rows,
                    "same_sha_recoveries": recoveries[:20],
                }
            )

    return result


def render(results):
    lines = [
        "# Independent Historical Flakiness Discovery — Wave 1",
        "",
        "Read-only scan of public repositories. No target repository is modified.",
        "",
        "| Repository | Runs | Reruns | Reruns with artifacts | JUnit | Bound JUnit | Same-SHA recovery runs |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        lines.append(
            f"| {item['repository']} | {item['runs_scanned']} | {item['rerun_runs']} | "
            f"{item['runs_with_artifacts']} | {item['runs_with_junit']} | "
            f"{item['runs_with_bound_junit']} | {item['runs_with_same_sha_recovery']} |"
        )

    lines.extend(["", "## Candidate runs", ""])
    any_candidate = False
    for item in results:
        for candidate in item["candidates"]:
            any_candidate = True
            lines.append(
                f"- **{item['repository']}** run `{candidate['run_id']}` "
                f"({candidate['workflow']}, attempts={candidate['attempts']}): "
                f"{len(candidate['same_sha_recoveries'])} same-SHA recovered tests."
            )
            for artifact in candidate["artifacts"][:10]:
                lines.append(
                    f"  - `{artifact['name']}`: attempt={artifact['attempt']}, "
                    f"binding={artifact['binding']}, observations={artifact['observations']}"
                )
    if not any_candidate:
        lines.append("No fully bound same-SHA JUnit recovery candidate was found in this wave.")

    return "\n".join(lines) + "\n"


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")

    raw = os.environ.get("EXTERNAL_BACKTEST_REPOSITORIES", "")
    repos = tuple(x.strip() for x in raw.split(",") if x.strip()) or DEFAULT_REPOSITORIES
    run_limit = max(50, min(int(os.environ.get("EXTERNAL_BACKTEST_RUN_LIMIT", "150")), 300))

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    results = []
    for repo in repos:
        try:
            results.append(discover_repository(api, repo, run_limit))
        except RuntimeError as exc:
            results.append(
                {
                    "repository": repo,
                    "runs_scanned": 0,
                    "rerun_runs": 0,
                    "runs_with_artifacts": 0,
                    "runs_with_junit": 0,
                    "runs_with_bound_junit": 0,
                    "runs_with_same_sha_recovery": 0,
                    "candidates": [],
                    "error": str(exc),
                }
            )

    report = render(results)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(report)


if __name__ == "__main__":
    main()
