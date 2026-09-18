from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass

from ci_retry_gate import GitHubAPI
from history_ci_waste import (
    POLICY_AUTO_RERUN_ONCE,
    HistoricalFailure,
    collect_history,
    summarize_history,
)
from recovery_ground_truth import RECOVERY_NOT_RECOVERED, is_validated_recovery

SHADOW_RECOVERED = "RECOVERED"
SHADOW_NOT_RECOVERED = "NOT_RECOVERED"
SHADOW_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ShadowDecision:
    fingerprint: str
    job_name: str
    category: str
    run_id: int
    outcome: str
    failed_minutes: float


@dataclass(frozen=True)
class ShadowFingerprintSummary:
    fingerprint: str
    job_name: str
    category: str
    decisions: int
    evaluated: int
    recoveries: int
    false_positives: int
    unknown_outcomes: int
    recoverable_failed_minutes: float

    @property
    def observed_precision(self) -> float:
        if self.evaluated <= 0:
            return 0.0
        return self.recoveries / self.evaluated


@dataclass(frozen=True)
class ShadowSummary:
    decisions: int
    evaluated: int
    recoveries: int
    false_positives: int
    unknown_outcomes: int
    recoverable_failed_minutes: float
    fingerprints: tuple[ShadowFingerprintSummary, ...]

    @property
    def observed_precision(self) -> float:
        if self.evaluated <= 0:
            return 0.0
        return self.recoveries / self.evaluated


def _policy_for_prior(prior: list[HistoricalFailure], fingerprint: str) -> str | None:
    same = [item for item in prior if item.fingerprint == fingerprint and item.attempt == 1]
    if not same:
        return None
    history = summarize_history(same, runs_analyzed=0)
    for policy in history.policies:
        if policy.fingerprint == fingerprint:
            return policy.policy
    return None


def simulate_shadow(failures: list[HistoricalFailure]) -> ShadowSummary:
    """Backtest learned policy using only evidence older than each simulated decision.

    Only first-attempt failures are shadow decisions because AUTO_RERUN_ONCE is the
    learned policy being validated. A decision with no real historical rerun is kept
    as UNKNOWN rather than guessed as success or failure.
    """
    ordered = sorted(
        failures,
        key=lambda item: (item.run_id, item.attempt, item.job_name, item.fingerprint),
    )
    prior: list[HistoricalFailure] = []
    decisions: list[ShadowDecision] = []

    for item in ordered:
        if item.attempt != 1:
            prior.append(item)
            continue

        policy = _policy_for_prior(prior, item.fingerprint)
        if policy == POLICY_AUTO_RERUN_ONCE:
            if is_validated_recovery(item.recovery_status):
                outcome = SHADOW_RECOVERED
            elif item.recovery_status == RECOVERY_NOT_RECOVERED:
                outcome = SHADOW_NOT_RECOVERED
            else:
                outcome = SHADOW_UNKNOWN
            decisions.append(
                ShadowDecision(
                    fingerprint=item.fingerprint,
                    job_name=item.job_name,
                    category=item.category,
                    run_id=item.run_id,
                    outcome=outcome,
                    failed_minutes=item.duration_minutes,
                )
            )

        prior.append(item)

    grouped: dict[str, list[ShadowDecision]] = defaultdict(list)
    for item in decisions:
        grouped[item.fingerprint].append(item)

    fp_summaries: list[ShadowFingerprintSummary] = []
    for fingerprint, items in grouped.items():
        recoveries = sum(item.outcome == SHADOW_RECOVERED for item in items)
        false_positives = sum(item.outcome == SHADOW_NOT_RECOVERED for item in items)
        unknown = sum(item.outcome == SHADOW_UNKNOWN for item in items)
        evaluated = recoveries + false_positives
        recoverable_minutes = round(
            sum(item.failed_minutes for item in items if item.outcome == SHADOW_RECOVERED),
            2,
        )
        first = items[0]
        fp_summaries.append(
            ShadowFingerprintSummary(
                fingerprint=fingerprint,
                job_name=first.job_name,
                category=first.category,
                decisions=len(items),
                evaluated=evaluated,
                recoveries=recoveries,
                false_positives=false_positives,
                unknown_outcomes=unknown,
                recoverable_failed_minutes=recoverable_minutes,
            )
        )

    fp_summaries.sort(
        key=lambda item: (-item.decisions, -item.observed_precision, item.fingerprint)
    )
    recoveries = sum(item.outcome == SHADOW_RECOVERED for item in decisions)
    false_positives = sum(item.outcome == SHADOW_NOT_RECOVERED for item in decisions)
    unknown = sum(item.outcome == SHADOW_UNKNOWN for item in decisions)
    evaluated = recoveries + false_positives
    recoverable_minutes = round(
        sum(item.failed_minutes for item in decisions if item.outcome == SHADOW_RECOVERED),
        2,
    )
    return ShadowSummary(
        decisions=len(decisions),
        evaluated=evaluated,
        recoveries=recoveries,
        false_positives=false_positives,
        unknown_outcomes=unknown,
        recoverable_failed_minutes=recoverable_minutes,
        fingerprints=tuple(fp_summaries),
    )


def render_shadow_report(summary: ShadowSummary) -> str:
    lines = [
        "## Policy Shadow Mode",
        "",
        "> Read-only retrospective backtest. No rerun is triggered. Each simulated decision uses only samples older than that decision.",
        "",
        f"Shadow AUTO_RERUN_ONCE decisions: **{summary.decisions}**",
        f"Decisions with a ground-truth-evaluable rerun outcome: **{summary.evaluated}**",
        f"Validated recoveries: **{summary.recoveries}**",
        f"Observed false positives: **{summary.false_positives}**",
        f"Unknown counterfactual outcomes: **{summary.unknown_outcomes}**",
        f"Ground-truth precision on evaluated decisions: **{summary.observed_precision:.1%}**",
        f"Recoverable failed-job runtime represented by observed recoveries: **{summary.recoverable_failed_minutes:.2f} min**",
        "",
    ]

    if summary.fingerprints:
        lines.extend(
            [
                "| Fingerprint | Job | Category | Decisions | Evaluated | Recoveries | False positives | Unknown | Precision | Recoverable failed runtime |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for item in summary.fingerprints[:10]:
            lines.append(
                f"| `{item.fingerprint}` | {item.job_name.replace('|', '/')} | `{item.category}` | "
                f"{item.decisions} | {item.evaluated} | {item.recoveries} | {item.false_positives} | "
                f"{item.unknown_outcomes} | {item.observed_precision:.1%} | {item.recoverable_failed_minutes:.2f} min |"
            )
    else:
        lines.append("No historical point had enough prior evidence to simulate AUTO_RERUN_ONCE yet.")

    lines.extend(
        [
            "",
            "> Recoverable failed-job runtime is evidence volume, not a claim of billed CI minutes saved. A rerun itself consumes runner time, and true savings depend on the workflow and human recovery path.",
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
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    run_id_raw = os.environ.get("INPUT_RUN_ID") or os.environ.get("GITHUB_RUN_ID")

    if not token or not repo or not run_id_raw:
        print("::warning::Policy shadow skipped because token, repository, or run ID is missing.")
        return 0

    try:
        run_id = int(run_id_raw)
        history_runs = max(0, min(int(os.environ.get("INPUT_HISTORY_RUNS", "20")), 50))
    except ValueError:
        print("::warning::Policy shadow skipped because run-id or history-runs is invalid.")
        return 0

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    try:
        current_run = api.get_run(repo, run_id)
        failures, _ = collect_history(api, repo, current_run, history_runs)
    except RuntimeError as exc:
        print(f"::warning::Policy shadow unavailable: {exc}")
        return 0

    summary = simulate_shadow(failures)
    report = render_shadow_report(summary)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n" + report)
    else:
        print(report)

    _write_output("shadow-decisions", str(summary.decisions))
    _write_output("shadow-evaluated-decisions", str(summary.evaluated))
    _write_output("shadow-recoveries", str(summary.recoveries))
    _write_output("shadow-false-positives", str(summary.false_positives))
    _write_output("shadow-unknown-outcomes", str(summary.unknown_outcomes))
    _write_output("shadow-observed-precision", f"{summary.observed_precision:.4f}")
    _write_output("shadow-recoverable-failed-minutes", f"{summary.recoverable_failed_minutes:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
