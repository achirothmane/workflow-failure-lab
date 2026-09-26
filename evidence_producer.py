"""Produce deterministic, policy-free evidence for CI failures.

The producer stops at facts and derived claims. It never decides whether an
action is allowed, never applies retry limits, and never triggers a rerun.
Those responsibilities belong to an Evidence Gate.
"""

from __future__ import annotations

from typing import Iterable, Protocol


EVIDENCE_BUNDLE_SCHEMA = "evidence-producer.ci.v1"


class JobAssessmentLike(Protocol):
    job_id: int
    name: str
    category: str
    confidence: str
    evidence: tuple[str, ...]
    provenance_status: str
    provenance_step: str
    provenance_command: str
    provenance_evidence: tuple[str, ...]
    failure_step_status: str
    failure_step: str
    failure_step_evidence: tuple[str, ...]
    side_effect_risk: bool
    side_effect_evidence: tuple[str, ...]
    duration_minutes: float


def _observed_at(run: dict) -> str | None:
    return (
        run.get("updated_at")
        or run.get("run_started_at")
        or run.get("created_at")
        or None
    )


def _observation(*, job: JobAssessmentLike, source: str, detail: str) -> dict:
    return {
        "kind": "OBSERVED",
        "source": source,
        "subject": {
            "job_id": job.job_id,
            "job_name": job.name,
        },
        "detail": detail,
    }


def _derived(
    *,
    job: JobAssessmentLike,
    claim: str,
    value: object,
    support: Iterable[str] = (),
) -> dict:
    return {
        "kind": "DERIVED",
        "claim": claim,
        "subject": {
            "job_id": job.job_id,
            "job_name": job.name,
        },
        "value": value,
        "support": list(support),
    }


def produce_ci_evidence_bundle(
    *,
    repo: str,
    run: dict,
    run_id: int,
    run_attempt: int,
    assessments: Iterable[JobAssessmentLike],
) -> dict:
    """Return a canonical CI evidence bundle without authorization semantics.

    V1 is deliberately deterministic:
    - OBSERVED records come from already-redacted CI log/metadata evidence.
    - DERIVED records expose deterministic classifier/provenance results.
    - INFERRED is present but empty; no model inference is silently promoted to fact.
    """

    items = list(assessments)
    observations: list[dict] = []
    derived: list[dict] = []
    missing_sources: list[str] = []
    contradictions: list[str] = []

    if not items:
        missing_sources.append("failed_jobs")

    for item in items:
        prefix = f"job:{item.job_id}"

        if item.evidence:
            observations.extend(
                _observation(
                    job=item,
                    source="github-actions.job-log",
                    detail=detail,
                )
                for detail in item.evidence
            )
        else:
            missing_sources.append(f"{prefix}:job-log-evidence")

        # Side-effect evidence originates in workflow/job metadata rather than
        # the policy that decides whether retrying is acceptable.
        observations.extend(
            _observation(
                job=item,
                source="github-actions.job-metadata",
                detail=detail,
            )
            for detail in item.side_effect_evidence
        )

        derived.extend(
            [
                _derived(
                    job=item,
                    claim="failure_category",
                    value=item.category,
                    support=item.evidence,
                ),
                _derived(
                    job=item,
                    claim="classification_confidence",
                    value=item.confidence,
                    support=item.evidence,
                ),
                _derived(
                    job=item,
                    claim="execution_provenance_status",
                    value=item.provenance_status,
                    support=item.provenance_evidence,
                ),
                _derived(
                    job=item,
                    claim="failure_step_status",
                    value=item.failure_step_status,
                    support=item.failure_step_evidence,
                ),
                _derived(
                    job=item,
                    claim="side_effect_risk",
                    value=item.side_effect_risk,
                    support=item.side_effect_evidence,
                ),
                _derived(
                    job=item,
                    claim="duration_minutes",
                    value=item.duration_minutes,
                ),
            ]
        )

        if not item.provenance_evidence:
            missing_sources.append(f"{prefix}:execution-provenance-evidence")
        if not item.failure_step_evidence:
            missing_sources.append(f"{prefix}:failure-step-evidence")
        if item.provenance_status == "UNAVAILABLE":
            missing_sources.append(f"{prefix}:execution-provenance")
        elif item.provenance_status == "MISMATCH":
            contradictions.append(f"{prefix}:execution-provenance-mismatch")

    # Stable order makes the bundle suitable for snapshots, artifacts and
    # later hashing/signing without nondeterministic list churn.
    missing_sources = sorted(set(missing_sources))
    contradictions = sorted(set(contradictions))

    return {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA,
        "producer": {
            "name": "workflow-failure-lab",
            "mode": "deterministic",
            "policy_free": True,
        },
        "subject": {
            "type": "ci_workflow_run",
            "repository": repo,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "head_sha": str(run.get("head_sha") or ""),
            "workflow_id": run.get("workflow_id"),
        },
        "observed_at": _observed_at(run),
        "observations": observations,
        "derived": derived,
        # Reserved explicitly so a future AI-assisted producer cannot blur
        # inference into observed or deterministic evidence.
        "inferred": [],
        "quality": {
            "status": "COMPLETE" if not missing_sources else "PARTIAL",
            "missing_sources": missing_sources,
            "contradictions": contradictions,
        },
    }
