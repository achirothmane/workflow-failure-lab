from __future__ import annotations

import json
import os
import re

from ci_retry_gate import GitHubAPI, classify_log


REPOSITORIES = [
    "PostHog/posthog",
    "DataDog/dd-trace-js",
    "ckan/ckan",
    "open-data/ckanext-canada",
    "open-data/ckanext-recombinant",
    "OCHA-DAP/hdx-ckan",
    "opennextjs/opennextjs-netlify",
    "opral/lix",
    "dxos/dxos",
    "ROCm/rocm-systems",
    "QwenLM/qwen-code",
    "gitbutlerapp/gitbutler",
    "shishobooks/shisho",
    "ZSeven-W/openpencil",
    "ArcadeData/arcadedb",
]

TEST_JOB_RE = re.compile(r"(test|pytest|vitest|jest|browser|e2e|integration|spec)", re.I)
JUNIT_RE = re.compile(r"(junit|test-results|pytest|nextest)", re.I)


def paged_jobs(api: GitHubAPI, repo: str, run_id: int, attempt: int) -> list[dict]:
    jobs = []
    for page in range(1, 6):
        data = api.request(
            "GET",
            f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}",
        )
        batch = list(data.get("jobs") or [])
        jobs.extend(batch)
        if len(batch) < 100:
            break
    return jobs


def discover_reruns(api: GitHubAPI, repo: str) -> list[dict]:
    found = []
    seen = set()
    for page in range(1, 6):
        data = api.request(
            "GET",
            f"/repos/{repo}/actions/runs?status=completed&per_page=100&page={page}",
        )
        batch = list(data.get("workflow_runs") or [])
        for run in batch:
            run_id = int(run.get("id") or 0)
            if run_id and run_id not in seen and int(run.get("run_attempt") or 1) > 1:
                seen.add(run_id)
                found.append(run)
                if len(found) >= 4:
                    return found
        if len(batch) < 100:
            break
    return found


def main() -> int:
    api = GitHubAPI(os.environ.get("GITHUB_TOKEN", ""))
    rows = []
    discovery = {}

    for repo in REPOSITORIES:
        try:
            reruns = discover_reruns(api, repo)
        except RuntimeError as exc:
            discovery[repo] = {"error": str(exc), "reruns": []}
            continue

        discovery[repo] = {
            "reruns": [
                {
                    "run_id": run.get("id"),
                    "attempt": run.get("run_attempt"),
                    "conclusion": run.get("conclusion"),
                    "workflow": run.get("name"),
                }
                for run in reruns
            ]
        }

        for run in reruns:
            run_id = int(run["id"])
            try:
                artifacts_data = api.request(
                    "GET",
                    f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
                )
                artifacts = list(artifacts_data.get("artifacts") or [])
                junit_names = sorted(
                    str(item.get("name") or "")
                    for item in artifacts
                    if JUNIT_RE.search(str(item.get("name") or ""))
                )
                failed_jobs = [
                    job for job in paged_jobs(api, repo, run_id, 1)
                    if str(job.get("conclusion") or "").lower() in {"failure", "timed_out"}
                ]
            except RuntimeError as exc:
                rows.append({
                    "repo": repo,
                    "run_id": run_id,
                    "error": str(exc),
                })
                continue

            for job in failed_jobs:
                name = str(job.get("name") or "")
                if not TEST_JOB_RE.search(name):
                    continue
                try:
                    log_text = api.get_job_logs(repo, int(job["id"]))
                    classification = classify_log(log_text)
                except RuntimeError as exc:
                    rows.append({
                        "repo": repo,
                        "run_id": run_id,
                        "job_id": job.get("id"),
                        "job": name,
                        "error": str(exc),
                    })
                    continue

                rows.append(
                    {
                        "repo": repo,
                        "run_id": run_id,
                        "run_conclusion": run.get("conclusion"),
                        "run_attempt": run.get("run_attempt"),
                        "job_id": job.get("id"),
                        "job": name,
                        "category": classification.category,
                        "confidence": classification.confidence,
                        "junit_artifacts": junit_names[:30],
                        "junit_artifact_count": len(junit_names),
                    }
                )

    unknown = [
        row for row in rows
        if row.get("category") == "UNKNOWN"
    ]
    unknown_with_junit = [
        row for row in unknown
        if int(row.get("junit_artifact_count") or 0) > 0
    ]
    summary = {
        "repositories_scanned": len(REPOSITORIES),
        "repositories_with_reruns": sum(
            bool(item.get("reruns")) for item in discovery.values()
        ),
        "test_jobs_scanned": sum("category" in row for row in rows),
        "unknown_test_jobs": len(unknown),
        "unknown_test_jobs_with_any_junit": len(unknown_with_junit),
        "unknown_candidates": unknown_with_junit,
        "discovery": discovery,
        "rows": rows,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
