"""Immutable Outcome and Reconciliation records for prior retry decisions."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from decision_record import verify_decision_record


OUTCOME_RECORD_SCHEMA = "ci-retry-gate.outcome-record.v1"
RECONCILIATION_RECORD_SCHEMA = "ci-retry-gate.reconciliation-record.v1"

_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out"})
_TERMINAL_CONCLUSIONS = frozenset(
    {
        "success",
        "failure",
        "timed_out",
        "cancelled",
        "skipped",
        "neutral",
        "action_required",
        "stale",
        "startup_failure",
    }
)


class OutcomeRecordError(ValueError):
    """Raised when outcome/reconciliation evidence is invalid or cannot be trusted."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _without_digest(record: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(record)
    value.pop("record_sha256", None)
    return value


def canonical_audit_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(
        _without_digest(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def audit_record_sha256(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_audit_bytes(record)).hexdigest()


def seal_audit_record(record: dict[str, Any]) -> dict[str, Any]:
    sealed = deepcopy(record)
    sealed["record_sha256"] = audit_record_sha256(sealed)
    return sealed


def _verify_digest(record: object, *, schema: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise OutcomeRecordError("audit record root must be an object")
    if record.get("schema_version") != schema:
        raise OutcomeRecordError(
            f"unsupported schema_version={record.get('schema_version')!r}"
        )

    embedded = str(record.get("record_sha256") or "").strip().lower()
    if len(embedded) != 64 or any(ch not in "0123456789abcdef" for ch in embedded):
        raise OutcomeRecordError("record_sha256 must be a SHA-256 hex digest")

    actual = audit_record_sha256(record)
    if embedded != actual:
        raise OutcomeRecordError(
            f"audit record SHA-256 mismatch: embedded {embedded}, observed {actual}"
        )
    return record


def _job_name(job: dict[str, Any]) -> str:
    return str(job.get("name") or f"job-{job.get('id') or 'unknown'}")


def _job_conclusion(job: dict[str, Any]) -> str:
    return str(job.get("conclusion") or "").strip().lower()


def _terminal_job_map(jobs: list[dict[str, Any]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for job in jobs:
        name = _job_name(job)
        conclusion = _job_conclusion(job)
        if conclusion:
            values[name] = conclusion
    return values


def bind_parent_decision_to_attempt(
    *,
    parent_decision: dict[str, Any],
    repository: str,
    run_id: int,
    current_run: dict[str, Any],
    current_attempt: int,
) -> tuple[bool, str]:
    """Bind a verified DER from N to the observed target attempt N+1."""
    parent = verify_decision_record(parent_decision)
    subject = parent["subject"]

    checks = (
        (
            str(subject.get("repository") or "") == str(repository),
            "repository",
        ),
        (
            int(subject.get("workflow_run_id") or 0) == int(run_id),
            "workflow_run_id",
        ),
        (
            int(subject.get("run_attempt") or 0) + 1 == int(current_attempt),
            "run_attempt",
        ),
        (
            str(subject.get("head_sha") or "")
            == str(current_run.get("head_sha") or ""),
            "head_sha",
        ),
        (
            subject.get("workflow_id") == current_run.get("workflow_id"),
            "workflow_id",
        ),
    )

    mismatches = [name for ok, name in checks if not ok]
    if mismatches:
        return False, "BINDING_MISMATCH:" + ",".join(mismatches)

    return True, "BOUND_TO_NEXT_ATTEMPT"


def build_outcome_record(
    *,
    parent_decision: dict[str, Any],
    current_run: dict[str, Any],
    previous_jobs: list[dict[str, Any]],
    current_jobs: list[dict[str, Any]],
    execution_receipt: dict[str, Any] | None,
    event_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Create immutable T2 observation for a verified prior decision."""
    parent = verify_decision_record(parent_decision)
    subject = parent["subject"]

    previous_map = _terminal_job_map(previous_jobs)
    current_map = _terminal_job_map(current_jobs)
    previous_failed = sorted(
        name for name, conclusion in previous_map.items() if conclusion in _FAILURE_CONCLUSIONS
    )
    current_failed = sorted(
        name for name, conclusion in current_map.items() if conclusion in _FAILURE_CONCLUSIONS
    )

    recovered = sorted(
        name
        for name in previous_failed
        if current_map.get(name) == "success"
    )
    recurrent = sorted(
        name
        for name in previous_failed
        if current_map.get(name) in _FAILURE_CONCLUSIONS
    )
    missing = sorted(
        name
        for name in previous_failed
        if name not in current_map
    )

    receipt_digest: str | None = None
    effect_attribution = "EXTERNAL_OR_UNKNOWN"
    if isinstance(execution_receipt, dict):
        integrity = execution_receipt.get("integrity")
        if isinstance(integrity, dict):
            candidate = str(integrity.get("digest") or "").strip().lower()
            if len(candidate) == 64 and all(ch in "0123456789abcdef" for ch in candidate):
                receipt_digest = candidate
        if execution_receipt.get("outcome") == "SUCCEEDED":
            effect_attribution = "GATE_DISPATCH_CONFIRMED"

    conclusion = str(current_run.get("conclusion") or "").strip().lower()
    if conclusion not in _TERMINAL_CONCLUSIONS:
        conclusion = conclusion or "unknown"

    return {
        "schema_version": OUTCOME_RECORD_SCHEMA,
        "event_id": str(event_id or uuid4()),
        "recorded_at": recorded_at or _now_iso(),
        "parent_decision_event_id": parent["event_id"],
        "parent_decision_sha256": parent["record_sha256"],
        "parent_execution_receipt_sha256": receipt_digest,
        "subject": {
            "repository": subject["repository"],
            "workflow_run_id": int(subject["workflow_run_id"]),
            "previous_attempt": int(subject["run_attempt"]),
            "observed_attempt": int(current_run.get("run_attempt") or 0),
            "head_sha": str(current_run.get("head_sha") or ""),
            "workflow_id": current_run.get("workflow_id"),
        },
        "observation": {
            "subsequent_attempt_observed": True,
            "workflow_status": str(current_run.get("status") or ""),
            "workflow_conclusion": conclusion,
            "effect_attribution": effect_attribution,
            "previous_failed_jobs": previous_failed,
            "recovered_jobs": recovered,
            "recurrent_jobs": recurrent,
            "unmatched_previous_failed_jobs": missing,
            "current_failed_jobs": current_failed,
        },
    }


def verify_outcome_record(record: object) -> dict[str, Any]:
    trusted = _verify_digest(record, schema=OUTCOME_RECORD_SCHEMA)
    subject = trusted.get("subject")
    observation = trusted.get("observation")
    if not isinstance(subject, dict):
        raise OutcomeRecordError("outcome subject must be an object")
    if not isinstance(observation, dict):
        raise OutcomeRecordError("outcome observation must be an object")
    if observation.get("subsequent_attempt_observed") is not True:
        raise OutcomeRecordError("outcome must represent an observed subsequent attempt")
    if not str(trusted.get("parent_decision_event_id") or "").strip():
        raise OutcomeRecordError("parent_decision_event_id is required")
    return trusted


def build_reconciliation_record(
    *,
    parent_decision: dict[str, Any],
    outcome_record: dict[str, Any],
    event_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Classify observed T2 evidence without claiming counterfactual correctness."""
    parent = verify_decision_record(parent_decision)
    outcome = verify_outcome_record(outcome_record)

    if outcome["parent_decision_event_id"] != parent["event_id"]:
        raise OutcomeRecordError("outcome does not reference the supplied parent decision")
    if outcome["parent_decision_sha256"] != parent["record_sha256"]:
        raise OutcomeRecordError("outcome parent digest does not match supplied decision")

    observation = outcome["observation"]
    recovered = list(observation.get("recovered_jobs") or [])
    recurrent = list(observation.get("recurrent_jobs") or [])
    missing = list(observation.get("unmatched_previous_failed_jobs") or [])
    attribution = str(observation.get("effect_attribution") or "EXTERNAL_OR_UNKNOWN")

    if parent["decision"] == "BLOCK":
        status = "SUBSEQUENT_ATTEMPT_AFTER_BLOCK"
        reason = (
            "A later attempt was observed after a BLOCK decision. This does not prove "
            "the BLOCK was wrong; the later execution may have used an external authority path."
        )
    elif attribution != "GATE_DISPATCH_CONFIRMED":
        status = "SUBSEQUENT_ATTEMPT_EXTERNAL_OR_UNKNOWN"
        reason = (
            "A later attempt was observed, but the prior gate dispatch could not be "
            "verified from the retained execution receipt."
        )
    elif recurrent and recovered:
        status = "PARTIAL_RECOVERY"
        reason = (
            "The gate-dispatched next attempt recovered some previously failed jobs "
            "while at least one prior failed job failed again."
        )
    elif recurrent:
        status = "RECURRENT_FAILURE"
        reason = (
            "The gate-dispatched next attempt repeated at least one previously failed "
            "job identity."
        )
    elif recovered and not missing:
        status = "RECOVERED_AFTER_RERUN"
        reason = (
            "The gate-dispatched next attempt observed success for every previously "
            "failed job identity represented in the prior attempt."
        )
    else:
        status = "OUTCOME_UNKNOWN"
        reason = (
            "A gate-dispatched next attempt was observed, but the available job mapping "
            "is insufficient for a stronger recovery claim."
        )

    return {
        "schema_version": RECONCILIATION_RECORD_SCHEMA,
        "event_id": str(event_id or uuid4()),
        "recorded_at": recorded_at or _now_iso(),
        "parent_decision_event_id": parent["event_id"],
        "parent_decision_sha256": parent["record_sha256"],
        "outcome_event_id": outcome["event_id"],
        "outcome_record_sha256": outcome["record_sha256"],
        "status": status,
        "reason": reason,
        "effect_attribution": attribution,
    }


def verify_reconciliation_record(record: object) -> dict[str, Any]:
    trusted = _verify_digest(record, schema=RECONCILIATION_RECORD_SCHEMA)
    if not str(trusted.get("status") or "").strip():
        raise OutcomeRecordError("reconciliation status is required")
    if not str(trusted.get("parent_decision_event_id") or "").strip():
        raise OutcomeRecordError("parent_decision_event_id is required")
    if not str(trusted.get("outcome_event_id") or "").strip():
        raise OutcomeRecordError("outcome_event_id is required")
    return trusted


def write_outcome_record(path: str | Path, record: dict[str, Any]) -> str:
    sealed = seal_audit_record(record)
    verify_outcome_record(sealed)
    return _write_record(path, sealed)


def write_reconciliation_record(path: str | Path, record: dict[str, Any]) -> str:
    sealed = seal_audit_record(record)
    verify_reconciliation_record(sealed)
    return _write_record(path, sealed)


def _write_record(path: str | Path, record: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return str(record["record_sha256"])
