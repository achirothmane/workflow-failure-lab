from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from benchmark_mode import collect_repository_history
from ci_retry_gate import GitHubAPI, PROVENANCE_CONFIRMED, TRANSIENT_CATEGORIES

FLEET_REPORT_SCHEMA = "ci-retry-gate.fleet-report.v1"


@dataclass(frozen=True, slots=True)
class FleetSummary:
    repository: str
    runs_analyzed: int
    failed_jobs: int
    rerun_eligible_jobs: int
    rerun_blocked_jobs: int
    observed_failed_minutes: float
    eligible_failed_minutes: float
    blocked_failed_minutes: float
    validated_candidate_recoveries: int
    candidate_failed_again: int
    candidate_unknown_outcomes: int
    blocked_reasons: tuple[tuple[str, int], ...]


def _value(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _duration(item: object) -> float:
    try:
        return max(0.0, float(_value(item, "duration_minutes", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _eligible(item: object) -> bool:
    return (
        str(_value(item, "category", "")) in TRANSIENT_CATEGORIES
        and str(_value(item, "confidence", "")) == "high"
        and str(_value(item, "provenance_status", "")) == PROVENANCE_CONFIRMED
        and _value(item, "side_effect_risk", False) is not True
    )


def _blocked_reason(item: object) -> str:
    if _value(item, "side_effect_risk", False) is True:
        return "SIDE_EFFECT_BOUNDARY"
    category = str(_value(item, "category", ""))
    confidence = str(_value(item, "confidence", ""))
    provenance = str(_value(item, "provenance_status", ""))
    if category == "CODE_REGRESSION":
        return "CODE_REGRESSION"
    if category == "UNKNOWN":
        return "UNKNOWN_CLASSIFICATION"
    if category == "EVIDENCE_UNAVAILABLE":
        return "EVIDENCE_UNAVAILABLE"
    if category in TRANSIENT_CATEGORIES and confidence != "high":
        return "LOW_CONFIDENCE_TRANSIENT"
    if (
        category in TRANSIENT_CATEGORIES
        and confidence == "high"
        and provenance != PROVENANCE_CONFIRMED
    ):
        return "UNCONFIRMED_EXECUTION_PROVENANCE"
    return "NON_TRANSIENT_CATEGORY"


def _recovery_bucket(item: object) -> str:
    status = str(_value(item, "recovery_status", ""))
    if status == "VALIDATED_RECOVERY":
        return "recovered"
    if status == "NOT_RECOVERED":
        return "failed_again"
    return "unknown"


def summarize_fleet(
    repository: str,
    failures: Iterable[object],
    *,
    runs_analyzed: int,
) -> FleetSummary:
    items = list(failures)
    eligible = [item for item in items if _eligible(item)]
    blocked = [item for item in items if not _eligible(item)]

    recovery_counts = Counter(_recovery_bucket(item) for item in eligible)
    blocked_reasons = Counter(_blocked_reason(item) for item in blocked)

    return FleetSummary(
        repository=repository,
        runs_analyzed=max(0, int(runs_analyzed)),
        failed_jobs=len(items),
        rerun_eligible_jobs=len(eligible),
        rerun_blocked_jobs=len(blocked),
        observed_failed_minutes=round(sum(_duration(item) for item in items), 2),
        eligible_failed_minutes=round(sum(_duration(item) for item in eligible), 2),
        blocked_failed_minutes=round(sum(_duration(item) for item in blocked), 2),
        validated_candidate_recoveries=recovery_counts["recovered"],
        candidate_failed_again=recovery_counts["failed_again"],
        candidate_unknown_outcomes=recovery_counts["unknown"],
        blocked_reasons=tuple(sorted(blocked_reasons.items())),
    )


def fleet_payload(summary: FleetSummary) -> dict[str, object]:
    evaluated = (
        summary.validated_candidate_recoveries + summary.candidate_failed_again
    )
    observed_candidate_precision = (
        summary.validated_candidate_recoveries / evaluated if evaluated else None
    )
    return {
        "schema_version": FLEET_REPORT_SCHEMA,
        "authority": "REPORT_ONLY",
        "repository": summary.repository,
        "runs_analyzed": summary.runs_analyzed,
        "jobs": {
            "failed": summary.failed_jobs,
            "rerun_eligible": summary.rerun_eligible_jobs,
            "rerun_blocked": summary.rerun_blocked_jobs,
        },
        "minutes": {
            "observed_failed": summary.observed_failed_minutes,
            "rerun_eligible_failed": summary.eligible_failed_minutes,
            "rerun_blocked_failed": summary.blocked_failed_minutes,
            "claimed_saved": None,
        },
        "candidate_outcomes": {
            "validated_recoveries": summary.validated_candidate_recoveries,
            "failed_again": summary.candidate_failed_again,
            "unknown": summary.candidate_unknown_outcomes,
            "observed_precision": observed_candidate_precision,
        },
        "blocked_reasons": dict(summary.blocked_reasons),
        "measurement_basis": (
            "This report is read-only. Runtime values are observed failed-job "
            "minutes, not billed CI savings. Candidate outcomes use only observed "
            "historical rerun evidence; unknown outcomes stay outside precision."
        ),
    }


def render_fleet_report(payload: dict[str, object]) -> str:
    jobs = payload["jobs"]
    minutes = payload["minutes"]
    outcomes = payload["candidate_outcomes"]
    blocked_reasons = payload["blocked_reasons"]
    precision = outcomes["observed_precision"]
    precision_text = "n/a" if precision is None else f"{float(precision):.3f}"

    lines = [
        "## CI Retry Gate — Fleet Report",
        "",
        f"Repository: `{payload['repository']}`",
        "",
        "| Runs analyzed | Failed jobs | Rerun-eligible | Blocked | Observed failed runtime |",
        "|---:|---:|---:|---:|---:|",
        (
            f"| {payload['runs_analyzed']} | {jobs['failed']} | "
            f"{jobs['rerun_eligible']} | {jobs['rerun_blocked']} | "
            f"{float(minutes['observed_failed']):.2f} min |"
        ),
        "",
        "### Candidate outcomes",
        "",
        (
            f"- Validated recoveries: **{outcomes['validated_recoveries']}**  "
            f"· failed again: **{outcomes['failed_again']}**  "
            f"· unknown: **{outcomes['unknown']}**"
        ),
        f"- Observed candidate precision: **{precision_text}**",
        "",
        "### Why jobs stayed blocked",
        "",
    ]
    if blocked_reasons:
        for reason, count in sorted(blocked_reasons.items()):
            lines.append(f"- `{reason}`: **{count}**")
    else:
        lines.append("- No blocked failed jobs in the sampled window.")

    lines.extend(
        [
            "",
            "### Value boundary",
            "",
            (
                f"- Observed failed runtime: **{float(minutes['observed_failed']):.2f} min**"
            ),
            (
                f"- Rerun-eligible failed runtime: "
                f"**{float(minutes['rerun_eligible_failed']):.2f} min**"
            ),
            (
                f"- Blocked failed runtime: "
                f"**{float(minutes['rerun_blocked_failed']):.2f} min**"
            ),
            "- Claimed CI minutes saved: **not asserted**",
            "",
            (
                "Fleet Report is report-only and cannot grant retry authority or "
                "mutate workflow runs."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    if not token:
        print("::error::github-token is required")
        return 2
    if not repo:
        print("::error::repository could not be determined")
        return 2

    try:
        run_limit = int(os.environ.get("INPUT_RUNS", "50"))
    except ValueError:
        print("::error::runs must be an integer")
        return 2
    if run_limit < 1 or run_limit > 200:
        print("::error::runs must be between 1 and 200")
        return 2

    api = GitHubAPI(str(token), os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    try:
        failures, runs_analyzed = collect_repository_history(api, repo, run_limit)
    except RuntimeError as exc:
        print(f"::error::fleet report could not read GitHub Actions history: {exc}")
        return 1

    summary = summarize_fleet(repo, failures, runs_analyzed=runs_analyzed)
    payload = fleet_payload(summary)
    report = render_fleet_report(payload)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)

    _write_output(
        "fleet-report-json",
        json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )
    _write_output("runs-analyzed", str(summary.runs_analyzed))
    _write_output("failed-jobs", str(summary.failed_jobs))
    _write_output("rerun-eligible-jobs", str(summary.rerun_eligible_jobs))
    _write_output("rerun-blocked-jobs", str(summary.rerun_blocked_jobs))
    _write_output(
        "observed-failed-minutes", f"{summary.observed_failed_minutes:.2f}"
    )
    _write_output(
        "eligible-failed-minutes", f"{summary.eligible_failed_minutes:.2f}"
    )
    _write_output(
        "blocked-failed-minutes", f"{summary.blocked_failed_minutes:.2f}"
    )
    _write_output(
        "validated-candidate-recoveries",
        str(summary.validated_candidate_recoveries),
    )
    _write_output("candidate-failed-again", str(summary.candidate_failed_again))
    _write_output(
        "candidate-unknown-outcomes", str(summary.candidate_unknown_outcomes)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
