from __future__ import annotations

import json
import os

from ci_retry_gate import GitHubAPI
from flaky_test_history import collect_flaky_history
from flaky_test_intelligence import FAIL, PASS
from historical_flakiness_shadow import compare_historical_flakiness_shadow

TARGET_REPO = "opral/lix"
TARGET_RUN = 36048130839
ARTIFACT_PREFIX = "rust-nextest-junit-e2e"

def main() -> int:
    api = GitHubAPI(os.environ.get("GITHUB_TOKEN", ""))
    run = api.get_run(TARGET_REPO, TARGET_RUN)

    history = collect_flaky_history(
        api,
        TARGET_REPO,
        run,
        history_runs=50,
        artifact_prefix=ARTIFACT_PREFIX,
    )

    shadow = compare_historical_flakiness_shadow(
        repo=TARGET_REPO,
        run_id=TARGET_RUN,
        run_attempt=1,
        observations=history.case_observations,
        baseline_decision="BLOCK",
        baseline_evidence_status="UNKNOWN",
    )

    current_attempt1_failures = [
        {
            "test_id": item.test_id,
            "sha": item.sha,
            "attempt": item.attempt,
            "status": item.status,
            "observed_at": item.observed_at,
        }
        for item in history.case_observations
        if item.run_id == TARGET_RUN and item.attempt == 1 and item.status == FAIL
    ]

    current_attempt2_passes = {
        item.test_id
        for item in history.case_observations
        if item.run_id == TARGET_RUN and item.attempt == 2 and item.status == PASS
    }

    recovered_current = [
        item["test_id"]
        for item in current_attempt1_failures
        if item["test_id"] in current_attempt2_passes
    ]

    payload = {
        "repository": TARGET_REPO,
        "run_id": TARGET_RUN,
        "head_sha": run.get("head_sha"),
        "runs_scanned": history.runs_scanned,
        "artifacts_seen": history.artifacts_seen,
        "artifacts_analyzed": history.artifacts_analyzed,
        "artifacts_skipped_ambiguous": history.artifacts_skipped_ambiguous,
        "observations": history.observations,
        "current_attempt1_failures": current_attempt1_failures,
        "current_recovered_on_attempt2": recovered_current,
        "shadow": shadow,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    if not current_attempt1_failures:
        raise SystemExit("expected at least one attempt-1 JUnit failure")
    if not recovered_current:
        raise SystemExit("expected current failure to recover on attempt 2")
    if shadow["authorization"]["changed"] is not False:
        raise SystemExit("shadow must never mutate production authorization")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
