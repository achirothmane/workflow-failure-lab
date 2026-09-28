from __future__ import annotations

import json
import os

from ci_retry_gate import GitHubAPI, classify_log
from flaky_test_history import collect_flaky_history
from flaky_test_intelligence import FAIL, PASS


TARGET_REPO = "DataDog/dd-trace-js"
TARGET_RUN = 36481666751
ARTIFACT_PREFIX = "junit-aws-sdk-8"


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    api = GitHubAPI(token)
    run = api.get_run(TARGET_REPO, TARGET_RUN)

    first_jobs = api.get_jobs_attempt(TARGET_REPO, TARGET_RUN, 1)
    failed_jobs = [
        job for job in first_jobs
        if str(job.get("conclusion") or "").lower() in {"failure", "timed_out"}
    ]
    classifications = []
    for job in failed_jobs:
        log_text = api.get_job_logs(TARGET_REPO, int(job["id"]))
        item = classify_log(log_text)
        classifications.append(
            {
                "job": job.get("name"),
                "category": item.category,
                "confidence": item.confidence,
            }
        )

    result = collect_flaky_history(
        api,
        TARGET_REPO,
        run,
        history_runs=1,
        artifact_prefix=ARTIFACT_PREFIX,
    )

    observations = [
        item for item in result.case_observations
        if item.run_id == TARGET_RUN
    ]
    by_test = {}
    for item in observations:
        by_test.setdefault(item.test_id, []).append(item)

    recovered = []
    for test_id, items in sorted(by_test.items()):
        failed_first = any(
            item.attempt == 1 and item.status == FAIL
            for item in items
        )
        passed_second = any(
            item.attempt == 2 and item.status == PASS
            for item in items
        )
        if failed_first and passed_second:
            recovered.append(test_id)

    payload = {
        "repository": TARGET_REPO,
        "run_id": TARGET_RUN,
        "run_attempt": run.get("run_attempt"),
        "failed_jobs": classifications,
        "artifacts_seen": result.artifacts_seen,
        "artifacts_analyzed": result.artifacts_analyzed,
        "artifacts_skipped_ambiguous": result.artifacts_skipped_ambiguous,
        "observations": result.observations,
        "attempts_observed": sorted({item.attempt for item in observations}),
        "same_sha_recovered_tests": recovered,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    if result.artifacts_analyzed < 2:
        raise SystemExit("expected both attempt artifacts to be analyzable")
    if result.artifacts_skipped_ambiguous != 0:
        raise SystemExit("trusted temporal binding should eliminate ambiguity")
    if not recovered:
        raise SystemExit("expected at least one observed fail-to-pass recovery")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
