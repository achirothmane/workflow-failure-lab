from __future__ import annotations

import hashlib
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from ci_retry_gate import (
    AMBIGUOUS,
    CAUSAL,
    FAILURE_CONCLUSIONS,
    PROVENANCE_CONFIRMED,
    TRANSIENT_CATEGORIES,
    GitHubAPI,
    assess_execution_provenance,
    causal_evidence_role,
    classify_log,
    detect_side_effect_risk,
    job_duration_minutes,
)
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_VALIDATED,
    assess_recovery_ground_truth,
    is_ground_truth_evaluable,
    is_validated_recovery,
    later_rerun_result,
)


_DYNAMIC_PATTERNS = (
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][0-9:.+\-Z]+\b", re.IGNORECASE), "<time>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"\b\d+\b"), "<n>"),
    (re.compile(r"\s+"), " "),
)

POLICY_AUTO_RERUN_ONCE = "AUTO_RERUN_ONCE"
POLICY_MANUAL_REVIEW = "MANUAL_REVIEW"
POLICY_DO_NOT_AUTO_RERUN = "DO_NOT_AUTO_RERUN"
MIN_POLICY_RERUN_SAMPLES = 5
MIN_AUTO_RECOVERY_RATE = 0.80
MAX_BLOCK_RECOVERY_RATE = 0.20
MIN_HIGH_CONFIDENCE_RATE = 0.80


@dataclass(frozen=True)
class HistoricalFailure:
    run_id: int
    job_name: str
    category: str
    confidence: str
    duration_minutes: float
    fingerprint: str = ""
    signature: str = ""
    recovered_after_rerun: bool = False
    rerun_observed: bool = False
    side_effect_risk: bool = False
    attempt: int = 1
    provenance_status: str = PROVENANCE_CONFIRMED
    recovery_status: str = RECOVERY_NOT_OBSERVED
    recovery_evidence: tuple[str, ...] = ()
    causal_evidence_count: int = 0
    ambiguous_evidence_count: int = 0


@dataclass(frozen=True)
class RecurringFailure:
    job_name: str
    category: str
    occurrences: int
    failed_minutes: float


@dataclass(frozen=True)
class FingerprintSummary:
    fingerprint: str
    job_name: str
    category: str
    signature: str
    occurrences: int
    failed_minutes: float
    rerun_observations: int
    rerun_recoveries: int
    high_confidence_occurrences: int
    side_effect_seen: bool
    validated_rerun_observations: int = 0
    validated_rerun_recoveries: int = 0

    @property
    def rerun_recovery_rate(self) -> float:
        if self.rerun_observations <= 0:
            return 0.0
        return self.rerun_recoveries / self.rerun_observations

    @property
    def ground_truth_recovery_rate(self) -> float:
        if self.validated_rerun_observations <= 0:
            return 0.0
        return self.validated_rerun_recoveries / self.validated_rerun_observations

    @property
    def high_confidence_rate(self) -> float:
        if self.occurrences <= 0:
            return 0.0
        return self.high_confidence_occurrences / self.occurrences


@dataclass(frozen=True)
class PolicyRecommendation:
    fingerprint: str
    policy: str
    reason: str
    rerun_samples: int
    recovery_rate: float
    high_confidence_rate: float


@dataclass(frozen=True)
class HistorySummary:
    runs_analyzed: int
    failure_records: int
    failed_minutes: float
    transient_waste_minutes: float
    recurring: tuple[RecurringFailure, ...]
    fingerprints: tuple[FingerprintSummary, ...] = ()
    policies: tuple[PolicyRecommendation, ...] = ()
    rerun_recoveries: int = 0
    validated_rerun_recoveries: int = 0


def normalize_signature_line(line: str) -> str:
    value = line.strip().lower()
    for pattern, replacement in _DYNAMIC_PATTERNS:
        value = pattern.sub(replacement, value)
    return value[:220]


def failure_fingerprint(job_name: str, category: str, evidence: tuple[str, ...]) -> tuple[str, str]:
    normalized_job = normalize_signature_line(job_name)
    normalized_evidence = [normalize_signature_line(line) for line in evidence if line.strip()]
    normalized_evidence = [line for line in normalized_evidence if line]
    signature = " | ".join(normalized_evidence[:2]) or f"{category.lower()} without stable evidence"
    raw = f"{normalized_job}\n{category}\n{signature}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:12].upper()
    return f"FG-{digest}", signature


def recommend_policy(item: FingerprintSummary) -> PolicyRecommendation:
    if item.side_effect_seen:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_DO_NOT_AUTO_RERUN,
            "A deploy/publish/migrate or other side-effect signal was observed for this fingerprint.",
            item.rerun_observations,
            item.rerun_recovery_rate,
            item.high_confidence_rate,
        )

    if item.category == "CODE_REGRESSION":
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_DO_NOT_AUTO_RERUN,
            "Code regressions require a code change rather than automatic retries.",
            item.rerun_observations,
            item.rerun_recovery_rate,
            item.high_confidence_rate,
        )

    if item.category not in TRANSIENT_CATEGORIES:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_MANUAL_REVIEW,
            f"{item.category} is not in the conservative transient allow-list.",
            item.rerun_observations,
            item.rerun_recovery_rate,
            item.high_confidence_rate,
        )

    if item.validated_rerun_observations < MIN_POLICY_RERUN_SAMPLES:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_MANUAL_REVIEW,
            (
                f"Only {item.validated_rerun_observations} ground-truth-evaluable rerun "
                f"samples are available; at least {MIN_POLICY_RERUN_SAMPLES} are required."
            ),
            item.validated_rerun_observations,
            item.ground_truth_recovery_rate,
            item.high_confidence_rate,
        )

    if item.high_confidence_rate < MIN_HIGH_CONFIDENCE_RATE:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_MANUAL_REVIEW,
            f"High-confidence classification rate is {item.high_confidence_rate:.0%}, below the {MIN_HIGH_CONFIDENCE_RATE:.0%} threshold.",
            item.validated_rerun_observations,
            item.ground_truth_recovery_rate,
            item.high_confidence_rate,
        )

    if item.ground_truth_recovery_rate >= MIN_AUTO_RECOVERY_RATE:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_AUTO_RERUN_ONCE,
            (
                f"Ground-truth validated recovery occurred after "
                f"{item.validated_rerun_recoveries}/{item.validated_rerun_observations} "
                f"evaluable reruns ({item.ground_truth_recovery_rate:.0%})."
            ),
            item.validated_rerun_observations,
            item.ground_truth_recovery_rate,
            item.high_confidence_rate,
        )

    if item.ground_truth_recovery_rate <= MAX_BLOCK_RECOVERY_RATE:
        return PolicyRecommendation(
            item.fingerprint,
            POLICY_DO_NOT_AUTO_RERUN,
            (
                f"Only {item.validated_rerun_recoveries}/{item.validated_rerun_observations} "
                f"ground-truth-evaluable reruns validated recovery "
                f"({item.ground_truth_recovery_rate:.0%})."
            ),
            item.validated_rerun_observations,
            item.ground_truth_recovery_rate,
            item.high_confidence_rate,
        )

    return PolicyRecommendation(
        item.fingerprint,
        POLICY_MANUAL_REVIEW,
        (
            f"Ground-truth recovery rate is {item.ground_truth_recovery_rate:.0%}; "
            "evidence is not decisive enough for automatic policy."
        ),
        item.validated_rerun_observations,
        item.ground_truth_recovery_rate,
        item.high_confidence_rate,
    )


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

    fp_counts: Counter[str] = Counter()
    fp_minutes: defaultdict[str, float] = defaultdict(float)
    fp_reruns: Counter[str] = Counter()
    fp_recoveries: Counter[str] = Counter()
    fp_high_confidence: Counter[str] = Counter()
    fp_validated_observations: Counter[str] = Counter()
    fp_validated_recoveries: Counter[str] = Counter()
    fp_side_effect: dict[str, bool] = defaultdict(bool)
    fp_example: dict[str, HistoricalFailure] = {}
    for item in failures:
        if not item.fingerprint:
            continue
        fp_counts[item.fingerprint] += 1
        fp_minutes[item.fingerprint] += item.duration_minutes
        if item.rerun_observed:
            fp_reruns[item.fingerprint] += 1
        if item.recovered_after_rerun:
            fp_recoveries[item.fingerprint] += 1
        if item.confidence == "high":
            fp_high_confidence[item.fingerprint] += 1
        if is_ground_truth_evaluable(item.recovery_status):
            fp_validated_observations[item.fingerprint] += 1
        if is_validated_recovery(item.recovery_status):
            fp_validated_recoveries[item.fingerprint] += 1
        if item.side_effect_risk:
            fp_side_effect[item.fingerprint] = True
        fp_example.setdefault(item.fingerprint, item)

    fingerprints = [
        FingerprintSummary(
            fingerprint=fingerprint,
            job_name=fp_example[fingerprint].job_name,
            category=fp_example[fingerprint].category,
            signature=fp_example[fingerprint].signature,
            occurrences=count,
            failed_minutes=round(fp_minutes[fingerprint], 2),
            rerun_observations=fp_reruns[fingerprint],
            rerun_recoveries=fp_recoveries[fingerprint],
            high_confidence_occurrences=fp_high_confidence[fingerprint],
            side_effect_seen=fp_side_effect[fingerprint],
            validated_rerun_observations=fp_validated_observations[fingerprint],
            validated_rerun_recoveries=fp_validated_recoveries[fingerprint],
        )
        for fingerprint, count in fp_counts.items()
    ]
    fingerprints.sort(
        key=lambda item: (
            -item.occurrences,
            -item.rerun_recoveries,
            -item.failed_minutes,
            item.fingerprint,
        )
    )
    policies = tuple(recommend_policy(item) for item in fingerprints)

    return HistorySummary(
        runs_analyzed=runs_analyzed,
        failure_records=len(failures),
        failed_minutes=failed_minutes,
        transient_waste_minutes=transient_waste_minutes,
        recurring=tuple(recurring),
        fingerprints=tuple(fingerprints),
        policies=policies,
        rerun_recoveries=sum(1 for item in failures if item.recovered_after_rerun),
        validated_rerun_recoveries=sum(
            1 for item in failures if is_validated_recovery(item.recovery_status)
        ),
    )


def render_history_report(summary: HistorySummary) -> str:
    recurring_fingerprints = [item for item in summary.fingerprints if item.occurrences >= 2]
    auto_count = sum(1 for item in summary.policies if item.policy == POLICY_AUTO_RERUN_ONCE)
    manual_count = sum(1 for item in summary.policies if item.policy == POLICY_MANUAL_REVIEW)
    blocked_count = sum(1 for item in summary.policies if item.policy == POLICY_DO_NOT_AUTO_RERUN)
    policy_by_fp = {item.fingerprint: item for item in summary.policies}

    lines = [
        "## CI History, Fingerprints & Policy Learning",
        "",
        f"Historical runs analyzed: **{summary.runs_analyzed}**",
        f"Failed jobs observed: **{summary.failure_records}**",
        f"Historical failed-job runtime: **{summary.failed_minutes:.2f} min**",
        f"High-confidence transient CI waste: **{summary.transient_waste_minutes:.2f} min**",
        f"Failure fingerprints observed: **{len(summary.fingerprints)}**",
        f"Jobs that later succeeded after a rerun: **{summary.rerun_recoveries}**",
        f"Ground-truth validated recoveries: **{summary.validated_rerun_recoveries}**",
        f"Learned policy recommendations: **{auto_count} auto-rerun · {manual_count} manual-review · {blocked_count} blocked**",
        "",
    ]

    if recurring_fingerprints:
        lines.extend(
            [
                "### Recurring failure fingerprints",
                "",
                "| Fingerprint | Job | Category | Occurrences | Real reruns | Later successes | GT evaluated | GT recoveries | Suggested policy | Failed runtime |",
                "|---|---|---|---:|---:|---:|---:|---:|---|---:|",
            ]
        )
        for item in recurring_fingerprints[:10]:
            policy = policy_by_fp[item.fingerprint]
            lines.append(
                f"| `{item.fingerprint}` | {item.job_name.replace('|', '/')} | `{item.category}` | "
                f"{item.occurrences} | {item.rerun_observations} | {item.rerun_recoveries} | "
                f"{item.validated_rerun_observations} | {item.validated_rerun_recoveries} | "
                f"`{policy.policy}` | {item.failed_minutes:.2f} min |"
            )
            lines.append(f"|  | Signature | `{item.signature.replace('`', "'")}` |  |  |  | {policy.reason.replace('|', '/')} |  |")
    else:
        lines.append("No exact failure fingerprint appeared at least twice in the sampled history.")

    if summary.recurring:
        lines.extend(
            [
                "",
                "### Broader recurring job/category patterns",
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

    lines.extend(
        [
            "",
            "> Policy Learning is advisory only. AUTO_RERUN_ONCE is suggested only for transient fingerprints with at least 5 ground-truth-evaluable rerun samples, at least 80% validated recovery, at least 80% high-confidence classifications, and no observed side-effect signal.",
            "> Fingerprints are deterministic hashes of the job, failure category, and normalized evidence lines. Timestamps, IP addresses, long hex IDs, and standalone numbers are normalized so the same underlying failure can match across runs.",
            "> Failed-job runtime is not automatically waste. The transient-waste figure counts only jobs whose logs match a high-confidence runner/infrastructure or dependency/network signature.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _jobs_for_attempt(api: GitHubAPI, repo: str, run_id: int, attempt: int) -> list[dict]:
    data = api.request(
        "GET",
        f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    )
    return list(data.get("jobs") or [])


def _later_rerun_outcome(
    attempt_jobs: dict[int, list[dict]],
    current_attempt: int,
    attempts: int,
    job_name: str,
    original_started_at: str,
) -> tuple[bool, bool]:
    """Backward-compatible raw rerun outcome; ground-truth validation is separate."""
    observed, recovered, _ = later_rerun_result(
        attempt_jobs,
        current_attempt,
        attempts,
        job_name,
        original_started_at,
    )
    return observed, recovered


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

        for attempt in range(1, attempts + 1):
            for job in attempt_jobs.get(attempt, []):
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
                causal_evidence_count = sum(
                    causal_evidence_role(line) == CAUSAL
                    for line in classification.evidence
                )
                ambiguous_evidence_count = sum(
                    causal_evidence_role(line) == AMBIGUOUS
                    for line in classification.evidence
                )
                provenance = assess_execution_provenance(job, log_text, classification)
                fingerprint, signature = failure_fingerprint(
                    job_name,
                    classification.category,
                    classification.evidence,
                )
                side_effect_risk, _ = detect_side_effect_risk(job)
                rerun_observed, recovered, rerun_job = later_rerun_result(
                    attempt_jobs,
                    attempt,
                    attempts,
                    job_name,
                    str(job.get("started_at") or ""),
                )
                recovery = assess_recovery_ground_truth(
                    original_job=job,
                    provenance_status=provenance.status,
                    provenance_step=provenance.step_name,
                    rerun_observed=rerun_observed,
                    recovered=recovered,
                    rerun_job=rerun_job,
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
                        attempt=attempt,
                        provenance_status=provenance.status,
                        recovery_status=recovery.status,
                        recovery_evidence=recovery.evidence,
                        causal_evidence_count=causal_evidence_count,
                        ambiguous_evidence_count=ambiguous_evidence_count,
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

    recurring_fingerprints = sum(1 for item in summary.fingerprints if item.occurrences >= 2)
    auto_policies = sum(1 for item in summary.policies if item.policy == POLICY_AUTO_RERUN_ONCE)
    manual_policies = sum(1 for item in summary.policies if item.policy == POLICY_MANUAL_REVIEW)
    blocked_policies = sum(1 for item in summary.policies if item.policy == POLICY_DO_NOT_AUTO_RERUN)
    _write_output("history-runs-analyzed", str(summary.runs_analyzed))
    _write_output("historical-failed-minutes", f"{summary.failed_minutes:.2f}")
    _write_output(
        "historical-transient-waste-minutes",
        f"{summary.transient_waste_minutes:.2f}",
    )
    _write_output("recurring-failures", str(len(summary.recurring)))
    _write_output("failure-fingerprints", str(len(summary.fingerprints)))
    _write_output("recurring-fingerprints", str(recurring_fingerprints))
    _write_output("rerun-recoveries", str(summary.rerun_recoveries))
    _write_output(
        "validated-rerun-recoveries",
        str(summary.validated_rerun_recoveries),
    )
    _write_output("policy-auto-rerun-fingerprints", str(auto_policies))
    _write_output("policy-manual-review-fingerprints", str(manual_policies))
    _write_output("policy-blocked-fingerprints", str(blocked_policies))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
