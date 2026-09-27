from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ci_retry_gate import (
    FAILURE_CONCLUSIONS,
    PROVENANCE_CONFIRMED,
    TRANSIENT_CATEGORIES,
    GitHubAPI,
    JobAssessment,
    _event_payload,
    _state_binding_token,
    _write_output,
    assess_job,
    detect_side_effect_risk,
)
from easl_state_binding import (
    StateBinding,
    StateBindingError,
    evaluate_required_state_bindings,
)


@dataclass(frozen=True)
class BlockedJob:
    assessment: JobAssessment
    reason: str


def selective_plan(
    assessments: list[JobAssessment],
    run_attempt: int,
    max_attempts: int,
    workflow_side_effect_risk: bool = False,
) -> tuple[list[JobAssessment], list[BlockedJob]]:
    """Return jobs that are individually safe to rerun and jobs that must stay blocked."""
    if run_attempt >= max_attempts:
        reason = f"Run attempt {run_attempt} reached max_attempts={max_attempts}."
        return [], [BlockedJob(item, reason) for item in assessments]

    if workflow_side_effect_risk:
        reason = (
            "The workflow contains a deploy/publish/migrate or other side-effect signal. "
            "GitHub may rerun dependent jobs when a job is rerun, so selective auto-rerun is blocked."
        )
        return [], [BlockedJob(item, reason) for item in assessments]

    safe: list[JobAssessment] = []
    blocked: list[BlockedJob] = []
    for item in assessments:
        if item.side_effect_risk:
            blocked.append(BlockedJob(item, "The failed job itself contains a side-effect signal."))
        elif item.category not in TRANSIENT_CATEGORIES:
            blocked.append(BlockedJob(item, f"{item.category} is not a transient category."))
        elif item.confidence != "high":
            blocked.append(BlockedJob(item, f"Transient classification confidence is {item.confidence}, not high."))
        elif item.provenance_status != PROVENANCE_CONFIRMED:
            blocked.append(
                BlockedJob(
                    item,
                    f"Execution provenance is {item.provenance_status}, not confirmed.",
                )
            )
        else:
            safe.append(item)
    return safe, blocked


def _selective_job_binding_value(job: dict | None) -> dict[str, object] | None:
    if job is None:
        return None
    return {
        "id": int(job.get("id") or 0),
        "name": str(job.get("name") or ""),
        "conclusion": str(job.get("conclusion") or "").lower(),
        "started_at": str(job.get("started_at") or ""),
        "completed_at": str(job.get("completed_at") or ""),
    }


def revalidate_selective_job_binding(
    api: GitHubAPI,
    repo: str,
    run_id: int,
    expected_run: dict,
    expected_job: dict,
) -> tuple[bool, str]:
    """Re-read one selective-rerun subject immediately before mutation.

    A selective rerun is authorized for one exact workflow/job execution state.
    The opaque binding covers the workflow attempt and the specific failed job
    whose transient evidence was assessed.
    """
    current_run = api.get_run(repo, run_id)
    current_jobs = api.get_jobs(repo, run_id)
    expected_job_id = int(expected_job.get("id") or 0)
    current_job = next(
        (
            job
            for job in current_jobs
            if int(job.get("id") or 0) == expected_job_id
        ),
        None,
    )

    expected_attempt = int(expected_run.get("run_attempt") or 0)
    current_attempt = int(current_run.get("run_attempt") or 0)
    expected_head_sha = str(expected_run.get("head_sha") or "")
    current_head_sha = str(current_run.get("head_sha") or "")
    expected_workflow_id = expected_run.get("workflow_id")
    current_workflow_id = current_run.get("workflow_id")

    bindings = (
        StateBinding(
            id="run-attempt",
            expected=_state_binding_token(expected_attempt),
            observed=_state_binding_token(current_attempt),
        ),
        StateBinding(
            id="head-sha",
            expected=_state_binding_token(expected_head_sha),
            observed=_state_binding_token(current_head_sha),
        ),
        StateBinding(
            id="workflow-id",
            expected=_state_binding_token(expected_workflow_id),
            observed=_state_binding_token(current_workflow_id),
        ),
        StateBinding(
            id="run-lifecycle",
            expected=_state_binding_token(
                {
                    "status": str(expected_run.get("status") or ""),
                    "conclusion": str(expected_run.get("conclusion") or ""),
                }
            ),
            observed=_state_binding_token(
                {
                    "status": str(current_run.get("status") or ""),
                    "conclusion": str(current_run.get("conclusion") or ""),
                }
            ),
        ),
        StateBinding(
            id="target-job",
            expected=_state_binding_token(_selective_job_binding_value(expected_job)),
            observed=_state_binding_token(_selective_job_binding_value(current_job)),
        ),
    )
    details = {
        "run-attempt": f"run_attempt {expected_attempt}->{current_attempt}",
        "head-sha": f"head_sha {expected_head_sha!r}->{current_head_sha!r}",
        "workflow-id": (
            f"workflow_id {expected_workflow_id!r}->{current_workflow_id!r}"
        ),
        "run-lifecycle": (
            "workflow lifecycle changed before selective rerun"
        ),
        "target-job": (
            f"job {expected_job_id} no longer matches the failed execution "
            "that produced the rerun evidence"
        ),
    }

    try:
        invalidations = evaluate_required_state_bindings(
            bindings,
            (
                "run-attempt",
                "head-sha",
                "workflow-id",
                "run-lifecycle",
                "target-job",
            ),
        )
    except StateBindingError as exc:
        return False, f"SELECTIVE_SCOPE_INVALID: {exc}."

    if invalidations:
        changed = [
            details[item.state_binding_id]
            for item in invalidations
            if item.state_binding_id in details
        ]
        return False, "SELECTIVE_SCOPE_CHANGED: " + "; ".join(changed) + "."

    return True, (
        "SELECTIVE_SCOPE_CONFIRMED: workflow attempt, head SHA, workflow, "
        "lifecycle, and target job still match the assessed failure."
    )


def _rerun_job(api: GitHubAPI, repo: str, job_id: int) -> None:
    """Rerun one GitHub Actions job (GitHub also reruns its dependent jobs)."""
    req = urllib.request.Request(
        f"{api.api_url}/repos/{repo}/actions/jobs/{job_id}/rerun",
        data=json.dumps({}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ci-retry-gate-action",
            "Content-Type": "application/json",
        },
    )
    try:
        with api.opener.open(req, timeout=30) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub job rerun failed for job {job_id} with HTTP {exc.code}: {body[:500]}"
        ) from exc


def render_selective_report(
    repo: str,
    run_id: int,
    safe: list[JobAssessment],
    blocked: list[BlockedJob],
    workflow_side_effects: list[str],
    triggered: list[JobAssessment],
) -> str:
    lines = [
        "## Selective Safe Rerun",
        "",
        f"Repository: `{repo}` · Run: `{run_id}`",
        "",
        f"Safe rerun candidates: **{len(safe)}** · Blocked failed jobs: **{len(blocked)}**",
        f"Selective reruns triggered: **{len(triggered)}**",
    ]

    if workflow_side_effects:
        lines.extend([
            "",
            "**Workflow-wide side-effect guard is active.** No selective rerun was allowed because GitHub can also rerun dependent jobs.",
            "",
            "Detected side-effect signals:",
        ])
        for hit in workflow_side_effects[:5]:
            lines.append(f"- `{hit.replace('`', "'")}`")

    if safe:
        lines.extend(["", "### Safe candidates", "", "| Job | Category | Confidence | Provenance |", "|---|---|---|---|"])
        for item in safe:
            lines.append(
                f"| {item.name.replace('|', '/')} | `{item.category}` | {item.confidence} | "
                f"`{item.provenance_status}` |"
            )

    if blocked:
        lines.extend(["", "### Blocked", "", "| Job | Category | Reason |", "|---|---|---|"])
        for item in blocked:
            lines.append(
                f"| {item.assessment.name.replace('|', '/')} | `{item.assessment.category}` | "
                f"{item.reason.replace('|', '/')} |"
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    event = _event_payload()
    workflow_run = event.get("workflow_run") or {}
    run_id_raw = os.environ.get("INPUT_RUN_ID") or workflow_run.get("id") or os.environ.get("GITHUB_RUN_ID")

    if not token:
        print("::error::github-token is required")
        return 2
    if not repo:
        print("::error::repository could not be determined")
        return 2
    try:
        run_id = int(run_id_raw)
    except (TypeError, ValueError):
        print("::error::run-id could not be determined")
        return 2

    try:
        max_attempts = int(os.environ.get("INPUT_MAX_ATTEMPTS", "2"))
    except ValueError:
        print("::error::max-attempts must be an integer")
        return 2

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    run = api.get_run(repo, run_id)
    run_attempt = int(run.get("run_attempt") or 1)
    jobs = api.get_jobs(repo, run_id)

    workflow_side_effects: list[str] = []
    for job in jobs:
        risk, evidence = detect_side_effect_risk(job)
        if risk:
            for hit in evidence:
                value = f"{job.get('name') or job.get('id')}: {hit}"
                if value not in workflow_side_effects:
                    workflow_side_effects.append(value)

    failed_jobs = [
        job for job in jobs
        if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS
    ]
    assessments: list[JobAssessment] = []
    for job in failed_jobs:
        job_id = int(job.get("id") or 0)
        try:
            logs = api.get_job_logs(repo, job_id)
        except RuntimeError as exc:
            logs = f"Unable to fetch logs: {exc}"
        assessments.append(assess_job(job, logs))

    safe, blocked = selective_plan(
        assessments,
        run_attempt=run_attempt,
        max_attempts=max_attempts,
        workflow_side_effect_risk=bool(workflow_side_effects),
    )

    triggered: list[JobAssessment] = []
    if safe:
        # One selective mutation per evaluated workflow-state epoch.
        #
        # GitHub's job-rerun endpoint also reruns dependent jobs. Once the first
        # mutation is accepted, the workflow state is known to be changing, so
        # the remaining pre-mutation justifications must not be reused as if the
        # original snapshot still held.
        candidate = min(safe, key=lambda item: item.job_id)
        expected_jobs = {
            int(job.get("id") or 0): job
            for job in failed_jobs
        }
        expected_job = expected_jobs.get(candidate.job_id)

        if expected_job is None:
            blocked.append(
                BlockedJob(
                    candidate,
                    "SELECTIVE_SCOPE_INVALID: assessed job is absent from the original failed-job snapshot.",
                )
            )
        else:
            try:
                binding_valid, binding_reason = revalidate_selective_job_binding(
                    api,
                    repo,
                    run_id,
                    run,
                    expected_job,
                )
            except RuntimeError as exc:
                binding_valid = False
                binding_reason = (
                    "SELECTIVE_SCOPE_UNAVAILABLE: could not re-read current workflow "
                    f"state before rerun: {exc}"
                )

            if not binding_valid:
                blocked.append(BlockedJob(candidate, binding_reason))
            else:
                try:
                    _rerun_job(api, repo, candidate.job_id)
                    triggered.append(candidate)
                except RuntimeError as exc:
                    blocked.append(BlockedJob(candidate, str(exc)))

        if triggered:
            mutated_job_id = triggered[0].job_id
            for item in safe:
                if item.job_id == mutated_job_id:
                    continue
                blocked.append(
                    BlockedJob(
                        item,
                        "SELECTIVE_STATE_EPOCH_ENDED: a prior selective rerun mutation "
                        "changed the workflow subject state; re-evaluate before another write.",
                    )
                )

    report = render_selective_report(repo, run_id, safe, blocked, workflow_side_effects, triggered)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)

    _write_output("selective-safe-jobs", str(len(safe)))
    _write_output("selective-blocked-jobs", str(len(blocked)))
    _write_output("selective-reruns-triggered", str(len(triggered)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
