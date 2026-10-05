from __future__ import annotations

import os
import re
from dataclasses import dataclass

from ci_retry_gate import (
    FAILURE_STEP_CONFIRMED,
    GitHubAPI,
    assess_failure_step_provenance,
    classify_log,
    detect_side_effect_risk,
)
from recovery_ground_truth import RECOVERY_VALIDATED, assess_recovery_ground_truth
from root_cause_precedence import (
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
    assess_causal_dominance,
)


DIRECT_VERIFIED = "DIRECT_VERIFIED"
DIRECT_REJECTED = "DIRECT_REJECTED"
DIRECT_UNRESOLVED = "DIRECT_UNRESOLVED"

PIPX_REPOSITORY = "pypa/pipx"
PIPX_RUN_ID = 31618954128
PIPX_FAILURE_ATTEMPT = 1
PIPX_RECOVERY_ATTEMPT = 2
PIPX_JOB_NAMES = (
    "🧪 test 3.12 - ubuntu-24.04",
    "🧪 test 3.15 - ubuntu-24.04",
)

_NETWORK_503_RE = re.compile(
    r"ERROR:\s+Could not install packages due to an OSError:.*"
    r"HTTPSConnectionPool\(host=['\"]github\.com['\"].*"
    r"too many 503 error responses",
    re.IGNORECASE,
)
_PACKAGE_SPEC_RE = re.compile(
    r"https://github\.com/wntrblm/nox/archive/2022\.1\.7\.zip",
    re.IGNORECASE,
)
_EXPECTED_INSTALL_ASSERT_RE = re.compile(
    r"assert\s+f?['\"]installed package.*captured\.out",
    re.IGNORECASE,
)
_EXIT_ASSERT_RE = re.compile(
    r"assert\s+not\s+run_pipx_cli\(\["
    r"['\"]install['\"].*wntrblm/nox/archive/2022\.1\.7\.zip",
    re.IGNORECASE,
)
_ASSERTION_TRACE_RE = re.compile(
    r"tests/test_install\.py:\d+:\s+AssertionError",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DirectVerification:
    job_name: str
    status: str
    baseline_category: str
    baseline_dominance_status: str
    recovery_status: str
    side_effect_risk: bool
    has_503_root_cause: bool
    has_matching_package_spec: bool
    has_downstream_assertion_shape: bool
    failed_step: str = ""
    evidence: tuple[str, ...] = ()
    error: str = ""

    @property
    def verified(self) -> bool:
        return self.status == DIRECT_VERIFIED


@dataclass(frozen=True)
class PipxDirectVerificationSummary:
    records: tuple[DirectVerification, ...]

    @property
    def verified_jobs(self) -> tuple[DirectVerification, ...]:
        return tuple(item for item in self.records if item.verified)

    @property
    def independent_verified_runs(self) -> int:
        return 1 if self.verified_jobs else 0

    @property
    def unresolved(self) -> int:
        return sum(item.status == DIRECT_UNRESOLVED for item in self.records)


def _jobs_for_attempt(
    api: GitHubAPI,
    repository: str,
    run_id: int,
    attempt: int,
) -> list[dict]:
    data = api.request(
        "GET",
        f"/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100",
    )
    return list(data.get("jobs") or [])


def _single_named_job(jobs: list[dict], name: str, conclusion: str) -> dict | None:
    matches = [
        job
        for job in jobs
        if str(job.get("name") or "") == name
        and str(job.get("conclusion") or "").lower() == conclusion
    ]
    return matches[0] if len(matches) == 1 else None


def _network_evidence(log_text: str) -> tuple[bool, bool, bool, tuple[str, ...]]:
    has_503 = bool(_NETWORK_503_RE.search(log_text))
    has_spec = bool(_PACKAGE_SPEC_RE.search(log_text))
    expected_assert = bool(_EXPECTED_INSTALL_ASSERT_RE.search(log_text))
    exit_assert = bool(_EXIT_ASSERT_RE.search(log_text))
    assertion_trace = bool(_ASSERTION_TRACE_RE.search(log_text))
    downstream_assertion = assertion_trace and (expected_assert or exit_assert)

    evidence: list[str] = []
    for raw in log_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _NETWORK_503_RE.search(line) and len(evidence) < 2:
            evidence.append(line[:280])
        elif _PACKAGE_SPEC_RE.search(line) and "assert" in line.lower() and len(evidence) < 4:
            evidence.append(line[:280])
        elif _ASSERTION_TRACE_RE.search(line) and len(evidence) < 5:
            evidence.append(line[:280])
    return has_503, has_spec, downstream_assertion, tuple(evidence)


def verify_pipx_case(
    api: GitHubAPI,
    job_name: str,
) -> DirectVerification:
    try:
        failed_jobs = _jobs_for_attempt(
            api,
            PIPX_REPOSITORY,
            PIPX_RUN_ID,
            PIPX_FAILURE_ATTEMPT,
        )
        rerun_jobs = _jobs_for_attempt(
            api,
            PIPX_REPOSITORY,
            PIPX_RUN_ID,
            PIPX_RECOVERY_ATTEMPT,
        )
        original = _single_named_job(failed_jobs, job_name, "failure")
        rerun = _single_named_job(rerun_jobs, job_name, "success")
        if original is None or rerun is None:
            return DirectVerification(
                job_name=job_name,
                status=DIRECT_UNRESOLVED,
                baseline_category="",
                baseline_dominance_status="",
                recovery_status="",
                side_effect_risk=True,
                has_503_root_cause=False,
                has_matching_package_spec=False,
                has_downstream_assertion_shape=False,
                error=(
                    f"original_found={original is not None} "
                    f"rerun_found={rerun is not None}"
                ),
            )

        log_text = api.get_job_logs(
            PIPX_REPOSITORY,
            int(original.get("id") or 0),
        )
    except RuntimeError as exc:
        return DirectVerification(
            job_name=job_name,
            status=DIRECT_UNRESOLVED,
            baseline_category="",
            baseline_dominance_status="",
            recovery_status="",
            side_effect_risk=True,
            has_503_root_cause=False,
            has_matching_package_spec=False,
            has_downstream_assertion_shape=False,
            error=str(exc)[:300],
        )

    classification = classify_log(log_text)
    dominance = assess_causal_dominance(original, log_text)
    failure_step = assess_failure_step_provenance(original)
    side_effect_risk, _ = detect_side_effect_risk(original)
    recovery = assess_recovery_ground_truth(
        original_job=original,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        rerun_observed=True,
        recovered=True,
        rerun_job=rerun,
    )
    has_503, has_spec, downstream_assertion, evidence = _network_evidence(log_text)

    # This direct verifier is intentionally narrower than root_cause_precedence:
    # it does not weaken the generic AssertionError blocker. It only recognizes
    # this pinned pipx shape where the assertion is an expectation on the output
    # / exit code of the exact GitHub download that failed with repeated 503s,
    # and the same job later re-executed successfully.
    verified = (
        classification.category == "CODE_REGRESSION"
        and dominance.status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE
        and failure_step.status == FAILURE_STEP_CONFIRMED
        and recovery.status == RECOVERY_VALIDATED
        and not side_effect_risk
        and has_503
        and has_spec
        and downstream_assertion
    )

    return DirectVerification(
        job_name=job_name,
        status=DIRECT_VERIFIED if verified else DIRECT_REJECTED,
        baseline_category=classification.category,
        baseline_dominance_status=dominance.status,
        recovery_status=recovery.status,
        side_effect_risk=side_effect_risk,
        has_503_root_cause=has_503,
        has_matching_package_spec=has_spec,
        has_downstream_assertion_shape=downstream_assertion,
        failed_step=failure_step.step_name,
        evidence=evidence,
    )


def verify_pipx_run(api: GitHubAPI) -> PipxDirectVerificationSummary:
    return PipxDirectVerificationSummary(
        tuple(verify_pipx_case(api, name) for name in PIPX_JOB_NAMES)
    )


def render_pipx_direct_verification(
    summary: PipxDirectVerificationSummary,
) -> str:
    lines = [
        "## pipx Direct Causal Verification",
        "",
        "> Research-only structural verifier. The generic deterministic blocker "
        "remains unchanged.",
        "",
        f"- Run: **{PIPX_REPOSITORY} #{PIPX_RUN_ID}**",
        f"- Jobs inspected: **{len(summary.records)}**",
        f"- Directly verified jobs: **{len(summary.verified_jobs)}**",
        f"- Independent verified runs contributed: **{summary.independent_verified_runs}**",
        f"- Unresolved: **{summary.unresolved}**",
        "",
        "| Job | Baseline | Generic dominance | Recovery | 503 | Assertion downstream | Side effect | Result |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in summary.records:
        lines.append(
            f"| {item.job_name} | `{item.baseline_category or '—'}` | "
            f"`{item.baseline_dominance_status or '—'}` | "
            f"`{item.recovery_status or '—'}` | "
            f"{'yes' if item.has_503_root_cause else 'no'} | "
            f"{'yes' if item.has_downstream_assertion_shape else 'no'} | "
            f"{'yes' if item.side_effect_risk else 'no'} | "
            f"`{item.status}` |"
        )
        for evidence in item.evidence:
            lines.append(f"|  | evidence | {evidence.replace('|', '/')} |  |  |  |  |  |")
        if item.error:
            lines.append(f"|  | error | {item.error.replace('|', '/')} |  |  |  |  |  |")

    lines.extend(
        [
            "",
            "> Multiple verified jobs from this workflow still count as **one** "
            "independent real positive-control run.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("::error::github-token is required")
        return 2

    summary = verify_pipx_run(GitHubAPI(token))
    report = render_pipx_direct_verification(summary)
    print(report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)

    if summary.unresolved:
        return 1
    if not summary.verified_jobs:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
