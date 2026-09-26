"""Evidence-only input boundary for CI retry authorization.

The gate consumes the canonical Evidence Producer bundle and execution policy.
It must not reach back into raw JobAssessment objects, logs, or source-system
metadata. That separation keeps evidence production reusable and makes the
authorization boundary explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evidence_producer import EVIDENCE_BUNDLE_SCHEMA


TRANSIENT_FAILURE_CATEGORIES = frozenset({"RUNNER_INFRA", "DEPENDENCY_NETWORK"})
_REQUIRED_JOB_CLAIMS = frozenset(
    {
        "failure_category",
        "classification_confidence",
        "execution_provenance_status",
        "side_effect_risk",
    }
)
_OPTIONAL_JOB_CLAIMS = frozenset({"failure_step_status"})
_JOB_CLAIMS = _REQUIRED_JOB_CLAIMS | _OPTIONAL_JOB_CLAIMS


@dataclass(frozen=True, slots=True)
class JobEvidence:
    job_id: int
    name: str
    category: str | None
    confidence: str | None
    provenance_status: str | None
    side_effect_risk: bool | None
    failure_step_status: str | None
    missing_claims: tuple[str, ...]
    conflicting_claims: tuple[str, ...]


class EvidenceBundleError(ValueError):
    """Raised when an object is not a supported Evidence Producer bundle."""


def _subject(bundle: dict[str, Any]) -> dict[str, Any]:
    subject = bundle.get("subject")
    if not isinstance(subject, dict):
        raise EvidenceBundleError("subject must be an object")
    return subject


def _validate_bundle(bundle: object) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise EvidenceBundleError("expected an EvidenceBundle object")
    if bundle.get("schema_version") != EVIDENCE_BUNDLE_SCHEMA:
        raise EvidenceBundleError(
            f"unsupported schema_version={bundle.get('schema_version')!r}"
        )
    producer = bundle.get("producer")
    if not isinstance(producer, dict) or producer.get("policy_free") is not True:
        raise EvidenceBundleError("producer.policy_free=true is required")
    _subject(bundle)
    derived = bundle.get("derived")
    if not isinstance(derived, list):
        raise EvidenceBundleError("derived must be an array")
    return bundle


def _job_evidence(bundle: object) -> list[JobEvidence]:
    data = _validate_bundle(bundle)

    values: dict[tuple[int, str], dict[str, object]] = {}
    conflicts: dict[tuple[int, str], set[str]] = {}

    for item in data["derived"]:
        if not isinstance(item, dict):
            continue
        claim = item.get("claim")
        if claim not in _JOB_CLAIMS:
            continue
        subject = item.get("subject")
        if not isinstance(subject, dict):
            continue
        raw_job_id = subject.get("job_id")
        try:
            job_id = int(raw_job_id)
        except (TypeError, ValueError):
            continue
        name = str(subject.get("job_name") or f"job-{job_id}")
        job_key = (job_id, name)
        job_values = values.setdefault(job_key, {})
        if claim in job_values and job_values[claim] != item.get("value"):
            conflicts.setdefault(job_key, set()).add(str(claim))
            continue
        job_values[claim] = item.get("value")

    jobs: list[JobEvidence] = []
    for job_key in sorted(values):
        job_id, name = job_key
        job_values = values[job_key]
        missing_set = set(_REQUIRED_JOB_CLAIMS.difference(job_values))
        if not isinstance(job_values.get("side_effect_risk"), bool):
            missing_set.add("side_effect_risk")
        missing = tuple(sorted(missing_set))
        jobs.append(
            JobEvidence(
                job_id=job_id,
                name=name,
                category=(
                    str(job_values["failure_category"])
                    if "failure_category" in job_values
                    else None
                ),
                confidence=(
                    str(job_values["classification_confidence"])
                    if "classification_confidence" in job_values
                    else None
                ),
                provenance_status=(
                    str(job_values["execution_provenance_status"])
                    if "execution_provenance_status" in job_values
                    else None
                ),
                side_effect_risk=(
                    job_values["side_effect_risk"]
                    if isinstance(job_values.get("side_effect_risk"), bool)
                    else None
                ),
                failure_step_status=(
                    str(job_values["failure_step_status"])
                    if "failure_step_status" in job_values
                    else None
                ),
                missing_claims=missing,
                conflicting_claims=tuple(sorted(conflicts.get(job_key, set()))),
            )
        )
    return jobs


def summarize_failed_jobs(bundle: object) -> list[dict[str, object]]:
    """Return the gate-facing failed-job summary derived only from the bundle."""
    try:
        jobs = _job_evidence(bundle)
    except EvidenceBundleError:
        return []
    return [
        {
            "job_id": job.job_id,
            "name": job.name,
            "category": job.category,
            "confidence": job.confidence,
            "provenance_status": job.provenance_status,
            "failure_step_status": job.failure_step_status,
            "side_effect_risk": job.side_effect_risk,
        }
        for job in jobs
    ]


def evidence_contradictions(bundle: object) -> list[str]:
    """Return contradictions relevant to retry evidence, never policy limits."""
    try:
        data = _validate_bundle(bundle)
        jobs = _job_evidence(data)
    except EvidenceBundleError:
        return []

    contradictions: list[str] = []

    quality = data.get("quality")
    if isinstance(quality, dict):
        raw = quality.get("contradictions")
        if isinstance(raw, list):
            contradictions.extend(str(item) for item in raw if item)

    for job in jobs:
        if job.side_effect_risk is True:
            contradictions.append(f"{job.name}: side_effect_risk")
        if (
            job.category is not None
            and job.category not in TRANSIENT_FAILURE_CATEGORIES
            and job.category != "UNKNOWN"
        ):
            contradictions.append(f"{job.name}: category={job.category}")
        if job.provenance_status == "MISMATCH":
            contradictions.append(f"{job.name}: provenance_mismatch")
        for claim in job.conflicting_claims:
            contradictions.append(f"{job.name}: conflicting_claim={claim}")

    return sorted(set(contradictions))


def assess_ci_retry_evidence(bundle: object) -> tuple[bool, str]:
    """Assess evidence sufficiency for a retry using the bundle only."""
    try:
        jobs = _job_evidence(bundle)
    except EvidenceBundleError as exc:
        return False, f"Evidence bundle is invalid: {exc}."

    if not jobs:
        return False, "No failed jobs were available to assess in the evidence bundle."

    incomplete = [
        job
        for job in jobs
        if job.missing_claims or job.conflicting_claims
    ]
    if incomplete:
        details = ", ".join(
            (
                f"{job.name}=missing({','.join(job.missing_claims)})"
                if job.missing_claims
                else f"{job.name}=conflicting({','.join(job.conflicting_claims)})"
            )
            for job in incomplete
        )
        return False, f"Evidence bundle is incomplete or internally inconsistent: {details}."

    if any(job.side_effect_risk is True for job in jobs):
        return (
            False,
            "At least one failed job contains a side-effect signal; blind rerun is blocked.",
        )

    unsafe = [
        job
        for job in jobs
        if job.category not in TRANSIENT_FAILURE_CATEGORIES
        or job.confidence != "high"
    ]
    if unsafe:
        names = ", ".join(
            f"{job.name}={job.category}/{job.confidence}" for job in unsafe
        )
        return (
            False,
            f"Not every failed job is a high-confidence transient failure: {names}.",
        )

    unproven = [job for job in jobs if job.provenance_status != "CONFIRMED"]
    if unproven:
        names = ", ".join(
            f"{job.name}={job.provenance_status}" for job in unproven
        )
        return False, f"Execution provenance was not confirmed for: {names}."

    return (
        True,
        "All failed jobs are high-confidence transient failures with confirmed "
        "execution provenance and no side-effect signal was found.",
    )


def decide_ci_retry(bundle: object, *, max_attempts: int) -> tuple[bool, str]:
    """Apply retry policy after evidence has been assessed."""
    evidence_safe, evidence_reason = assess_ci_retry_evidence(bundle)
    if not evidence_safe:
        return False, evidence_reason

    try:
        data = _validate_bundle(bundle)
        run_attempt = int(_subject(data).get("run_attempt"))
    except (EvidenceBundleError, TypeError, ValueError):
        return False, "Evidence bundle subject is missing a valid run_attempt."

    if max_attempts < 1:
        return False, "Execution policy is invalid: max_attempts must be positive."

    if run_attempt >= max_attempts:
        return False, (
            "Evidence supports a safe retry, but execution policy blocks it: "
            f"run_attempt={run_attempt} reached max_attempts={max_attempts}."
        )

    return True, evidence_reason


EVIDENCE_DECISION_SCHEMA = "ci-retry-gate.evidence-decision.v1"


def build_ci_retry_decision(bundle: object, *, max_attempts: int) -> dict[str, Any]:
    """Build the complete authorization contract from EvidenceBundle + policy only."""
    safe, reason = decide_ci_retry(bundle, max_attempts=max_attempts)
    contradictions = evidence_contradictions(bundle)

    if safe:
        evidence_status = "SUFFICIENT"
        confidence = "high"
    elif contradictions:
        evidence_status = "CONTRADICTED"
        confidence = "high"
    else:
        evidence_status = "UNKNOWN"
        confidence = "unknown"

    data = bundle if isinstance(bundle, dict) else {}
    subject = data.get("subject")
    if not isinstance(subject, dict):
        subject = {}

    return {
        "schema_version": EVIDENCE_DECISION_SCHEMA,
        "action": "rerun_ci",
        "decision": "ALLOW" if safe else "BLOCK",
        "evidence_status": evidence_status,
        "confidence": confidence,
        "observed_at": data.get("observed_at"),
        "fresh_until": None,
        "freshness_basis": (
            "Scoped to repository/run_id/run_attempt/head_sha; recompute after any "
            "workflow state, attempt, or head SHA change."
        ),
        "scope": {
            "repository": str(subject.get("repository") or ""),
            "run_id": subject.get("run_id"),
            "run_attempt": subject.get("run_attempt"),
            "head_sha": str(subject.get("head_sha") or ""),
            "workflow_id": subject.get("workflow_id"),
        },
        "policy": {"max_attempts": max_attempts},
        "evidence_bundle": bundle if isinstance(bundle, dict) else None,
        "reasons": [reason],
        "contradictions": contradictions,
        "failed_jobs": summarize_failed_jobs(bundle),
        "rerun_triggered": False,
    }
