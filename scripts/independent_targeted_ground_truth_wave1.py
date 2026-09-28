from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from benchmark_mode import _collect_failures_for_runs, _rejection_reason
from ci_retry_gate import GitHubAPI
from recovery_ground_truth import RECOVERY_NOT_RECOVERED, RECOVERY_VALIDATED


TARGETS = {
    "DataDog/dd-trace-js": [
        36495931875,
        36483596838,
        36481666751,
        36481666587,
    ],
    "ckan/ckan": [
        36104227064,
        36103073165,
    ],
    "open-telemetry/opentelemetry-dotnet": [
        36425264396,
    ],
}


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    api = GitHubAPI(token)

    records = []
    category_counts = Counter()
    recovery_by_category = Counter()
    failed_again_by_category = Counter()
    recovery_by_rejection = Counter()
    failed_again_by_rejection = Counter()

    for repo, run_ids in TARGETS.items():
        runs = [api.get_run(repo, run_id) for run_id in run_ids]
        failures = _collect_failures_for_runs(api, repo, runs)
        for item in failures:
            category_counts[item.category] += 1
            rejection = _rejection_reason(item) or "ELIGIBLE"
            if item.recovery_status == RECOVERY_VALIDATED:
                recovery_by_category[item.category] += 1
                recovery_by_rejection[rejection] += 1
            elif item.recovery_status == RECOVERY_NOT_RECOVERED:
                failed_again_by_category[item.category] += 1
                failed_again_by_rejection[rejection] += 1

            records.append(
                {
                    "repository": repo,
                    "run_id": item.run_id,
                    "job": item.job_name,
                    "category": item.category,
                    "confidence": item.confidence,
                    "rejection_reason": rejection,
                    "recovery_status": item.recovery_status,
                    "rerun_observed": item.rerun_observed,
                    "recovered_after_rerun": item.recovered_after_rerun,
                    "failure_step_status": item.failure_step_status,
                    "provenance_status": item.provenance_status,
                    "side_effect_risk": item.side_effect_risk,
                }
            )

    payload = {
        "sample": {
            "repositories": len(TARGETS),
            "runs": sum(len(v) for v in TARGETS.values()),
            "failed_jobs": len(records),
        },
        "category_counts": dict(sorted(category_counts.items())),
        "validated_recoveries_by_category": dict(sorted(recovery_by_category.items())),
        "failed_again_by_category": dict(sorted(failed_again_by_category.items())),
        "validated_recoveries_by_rejection_reason": dict(sorted(recovery_by_rejection.items())),
        "failed_again_by_rejection_reason": dict(sorted(failed_again_by_rejection.items())),
        "records": records,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))

    code_recovery = recovery_by_category.get("CODE_REGRESSION", 0)
    unknown_recovery = recovery_by_category.get("UNKNOWN", 0)
    print()
    print(
        "GROUND_TRUTH_SUMMARY "
        f"code_regression_recoveries={code_recovery} "
        f"unknown_recoveries={unknown_recovery}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
