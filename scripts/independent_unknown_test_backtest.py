from __future__ import annotations

import json
import os
import re

from ci_retry_gate import GitHubAPI, classify_log


TARGETS = [
    ("DataDog/dd-trace-js", 36495931875),
    ("DataDog/dd-trace-js", 36481666751),
    ("DataDog/dd-trace-js", 36483596838),
    ("ckan/ckan", 36104227064),
    ("ckan/ckan", 36103073165),
    ("open-data/ckanext-canada", 36417499202),
    ("opennextjs/opennextjs-netlify", 36340294286),
    ("opral/lix", 36163714209),
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


def main() -> int:
    api = GitHubAPI(os.environ.get("GITHUB_TOKEN", ""))
    rows = []

    for repo, run_id in TARGETS:
        run = api.get_run(repo, run_id)
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

        for job in failed_jobs:
            name = str(job.get("name") or "")
            if not TEST_JOB_RE.search(name):
                continue
            log_text = api.get_job_logs(repo, int(job["id"]))
            classification = classify_log(log_text)
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
                    "junit_artifacts": junit_names[:20],
                    "junit_artifact_count": len(junit_names),
                }
            )

    summary = {
        "jobs_scanned": len(rows),
        "unknown_test_jobs": [
            row for row in rows if row["category"] == "UNKNOWN"
        ],
        "rows": rows,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
