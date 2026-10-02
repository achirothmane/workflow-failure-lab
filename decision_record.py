"""Canonical Decision Evidence Record (DER) construction and verification."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DECISION_RECORD_SCHEMA = "ci-retry-gate.decision-record.v1"
AUTHORIZATION_PATHS = frozenset({"POLICY", "HUMAN_OVERRIDE"})
IDENTITY_TYPES = frozenset({"human", "github_app", "token", "bot", "unknown"})


class DecisionRecordError(ValueError):
    """Raised when a Decision Evidence Record cannot be trusted or decoded."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _record_without_digest(record: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(record)
    value.pop("record_sha256", None)
    return value


def canonical_decision_record_bytes(record: dict[str, Any]) -> bytes:
    """Return deterministic bytes for the DER semantic payload.

    The embedded digest is deliberately excluded to avoid self-reference.
    """
    return json.dumps(
        _record_without_digest(record),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def decision_record_sha256(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_decision_record_bytes(record)).hexdigest()


def _validate_identity(name: str, identity: object) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise DecisionRecordError(f"identity {name!r} must be an object")
    raw = str(identity.get("raw") or "").strip()
    identity_type = str(identity.get("identity_type") or "").strip()
    if not raw:
        raise DecisionRecordError(f"identity {name!r} requires raw")
    if identity_type not in IDENTITY_TYPES:
        raise DecisionRecordError(
            f"identity {name!r} has unsupported identity_type={identity_type!r}"
        )
    return {"raw": raw, "identity_type": identity_type}


def _validate_parent(parent: object, *, current_attempt: int) -> dict[str, Any] | None:
    if parent is None:
        return None
    if not isinstance(parent, dict):
        raise DecisionRecordError("parent_decision must be an object")

    event_id = str(parent.get("event_id") or "").strip()
    digest = str(parent.get("record_sha256") or "").strip().lower()
    try:
        run_attempt = int(parent.get("run_attempt"))
    except (TypeError, ValueError) as exc:
        raise DecisionRecordError("parent_decision.run_attempt must be an integer") from exc

    if not event_id:
        raise DecisionRecordError("parent_decision.event_id is required")
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DecisionRecordError("parent_decision.record_sha256 must be a SHA-256 hex digest")
    if run_attempt < 1:
        raise DecisionRecordError("parent_decision.run_attempt must be positive")
    if run_attempt >= current_attempt:
        raise DecisionRecordError(
            "parent_decision.run_attempt must precede the current run_attempt"
        )

    return {
        "event_id": event_id,
        "record_sha256": digest,
        "run_attempt": run_attempt,
    }


def _scope_from_decision(evidence_decision: dict[str, Any]) -> dict[str, Any]:
    scope = evidence_decision.get("scope")
    if not isinstance(scope, dict):
        raise DecisionRecordError("evidence decision scope must be an object")

    repository = str(scope.get("repository") or "").strip()
    head_sha = str(scope.get("head_sha") or "").strip()
    if not repository:
        raise DecisionRecordError("evidence decision scope.repository is required")
    if not head_sha:
        raise DecisionRecordError("evidence decision scope.head_sha is required")

    try:
        run_id = int(scope.get("run_id"))
        run_attempt = int(scope.get("run_attempt"))
    except (TypeError, ValueError) as exc:
        raise DecisionRecordError(
            "evidence decision scope requires integer run_id and run_attempt"
        ) from exc

    if run_id < 1 or run_attempt < 1:
        raise DecisionRecordError("run_id and run_attempt must be positive")

    return {
        "repository": repository,
        "workflow_run_id": run_id,
        "run_attempt": run_attempt,
        "head_sha": head_sha,
        "workflow_id": scope.get("workflow_id"),
    }


def build_decision_record(
    *,
    evidence_decision: dict[str, Any],
    evidence_bundle_sha256: str,
    policy_ref: str,
    authorization_path: str,
    next_action: str,
    identities: dict[str, dict[str, str]],
    override: dict[str, Any] | None = None,
    parent_decision: dict[str, Any] | None = None,
    event_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build an unsealed DER from the finalized retry decision."""
    decision = str(evidence_decision.get("decision") or "")
    if decision not in {"ALLOW", "BLOCK"}:
        raise DecisionRecordError("decision must be ALLOW or BLOCK")

    evidence_status = str(evidence_decision.get("evidence_status") or "").strip()
    if not evidence_status:
        raise DecisionRecordError("evidence_status is required")

    digest = evidence_bundle_sha256.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DecisionRecordError("evidence_bundle_sha256 must be a SHA-256 hex digest")

    policy = policy_ref.strip()
    if not policy:
        raise DecisionRecordError("policy_ref is required")

    path = authorization_path.strip()
    if path not in AUTHORIZATION_PATHS:
        raise DecisionRecordError(
            f"authorization_path must be one of {sorted(AUTHORIZATION_PATHS)}"
        )

    action = next_action.strip()
    if not action:
        raise DecisionRecordError("next_action is required")

    normalized_identities = {
        name: _validate_identity(name, identity)
        for name, identity in sorted(identities.items())
    }
    if "decision_engine" not in normalized_identities:
        raise DecisionRecordError("identities.decision_engine is required")

    normalized_override: dict[str, Any] | None = None
    if path == "HUMAN_OVERRIDE":
        if not isinstance(override, dict):
            raise DecisionRecordError("HUMAN_OVERRIDE requires override metadata")
        reason = str(override.get("reason") or "").strip()
        if not reason:
            raise DecisionRecordError("human override requires a non-empty reason")
        actor = _validate_identity("override.actor", override.get("actor"))
        original_event_id = str(override.get("original_decision_event_id") or "").strip()
        if not original_event_id:
            raise DecisionRecordError(
                "human override requires original_decision_event_id"
            )
        normalized_override = {
            "actor": actor,
            "reason": reason,
            "authority_source": (
                str(override.get("authority_source") or "").strip() or None
            ),
            "original_decision_event_id": original_event_id,
        }
    elif override is not None:
        raise DecisionRecordError("override metadata requires HUMAN_OVERRIDE authorization_path")

    subject = _scope_from_decision(evidence_decision)
    parent = _validate_parent(
        parent_decision,
        current_attempt=int(subject["run_attempt"]),
    )

    reasons = evidence_decision.get("reasons")
    reason = ""
    if isinstance(reasons, list) and reasons:
        reason = str(reasons[0])

    record: dict[str, Any] = {
        "schema_version": DECISION_RECORD_SCHEMA,
        "event_id": str(event_id or uuid4()),
        "recorded_at": recorded_at or _now_iso(),
        "subject": subject,
        "decision": decision,
        "evidence_status": evidence_status,
        "reason": reason,
        "evidence_bundle_sha256": digest,
        "policy_ref": policy,
        "authorization_path": path,
        "next_action": action,
        "identities": normalized_identities,
        "override": normalized_override,
        "parent_decision": parent,
    }
    return record


def seal_decision_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy carrying the digest of the canonical semantic record."""
    sealed = deepcopy(record)
    sealed["record_sha256"] = decision_record_sha256(sealed)
    return sealed


def verify_decision_record(
    record: object,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate schema and digest, returning the trusted record on success."""
    if not isinstance(record, dict):
        raise DecisionRecordError("decision record root must be an object")
    if record.get("schema_version") != DECISION_RECORD_SCHEMA:
        raise DecisionRecordError(
            f"unsupported schema_version={record.get('schema_version')!r}"
        )

    embedded = str(record.get("record_sha256") or "").strip().lower()
    if len(embedded) != 64 or any(ch not in "0123456789abcdef" for ch in embedded):
        raise DecisionRecordError("record_sha256 must be a SHA-256 hex digest")

    actual = decision_record_sha256(record)
    if actual != embedded:
        raise DecisionRecordError(
            f"decision record SHA-256 mismatch: embedded {embedded}, observed {actual}"
        )

    if expected_sha256 is not None:
        expected = expected_sha256.strip().lower()
        if not expected or actual != expected:
            raise DecisionRecordError(
                f"decision record SHA-256 mismatch: expected {expected or '<empty>'}, observed {actual}"
            )

    # Re-validate semantic fields without regenerating identity or timestamps.
    decision = str(record.get("decision") or "")
    if decision not in {"ALLOW", "BLOCK"}:
        raise DecisionRecordError("decision must be ALLOW or BLOCK")

    subject = record.get("subject")
    if not isinstance(subject, dict):
        raise DecisionRecordError("subject must be an object")
    try:
        run_attempt = int(subject.get("run_attempt"))
        run_id = int(subject.get("workflow_run_id"))
    except (TypeError, ValueError) as exc:
        raise DecisionRecordError("subject run identifiers must be integers") from exc
    if run_attempt < 1 or run_id < 1:
        raise DecisionRecordError("subject run identifiers must be positive")
    if not str(subject.get("repository") or "").strip():
        raise DecisionRecordError("subject.repository is required")
    if not str(subject.get("head_sha") or "").strip():
        raise DecisionRecordError("subject.head_sha is required")

    evidence_digest = str(record.get("evidence_bundle_sha256") or "").strip().lower()
    if len(evidence_digest) != 64 or any(
        ch not in "0123456789abcdef" for ch in evidence_digest
    ):
        raise DecisionRecordError("evidence_bundle_sha256 must be a SHA-256 hex digest")

    path = str(record.get("authorization_path") or "")
    if path not in AUTHORIZATION_PATHS:
        raise DecisionRecordError("unsupported authorization_path")

    identities = record.get("identities")
    if not isinstance(identities, dict) or "decision_engine" not in identities:
        raise DecisionRecordError("identities.decision_engine is required")
    for name, identity in identities.items():
        _validate_identity(str(name), identity)

    override = record.get("override")
    if path == "HUMAN_OVERRIDE":
        if not isinstance(override, dict):
            raise DecisionRecordError("HUMAN_OVERRIDE requires override metadata")
        if not str(override.get("reason") or "").strip():
            raise DecisionRecordError("human override requires a non-empty reason")
        _validate_identity("override.actor", override.get("actor"))
    elif override is not None:
        raise DecisionRecordError("POLICY authorization cannot contain override metadata")

    _validate_parent(record.get("parent_decision"), current_attempt=run_attempt)

    if not str(record.get("policy_ref") or "").strip():
        raise DecisionRecordError("policy_ref is required")
    if not str(record.get("next_action") or "").strip():
        raise DecisionRecordError("next_action is required")

    return record


def write_decision_record(path: str | Path, record: dict[str, Any]) -> str:
    """Seal and atomically persist a DER. Returns the semantic record digest."""
    sealed = seal_decision_record(record)
    verify_decision_record(sealed)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        sealed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return str(sealed["record_sha256"])


def read_decision_record(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Read and verify a persisted DER before any caller can trust it."""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise DecisionRecordError(f"could not read decision record: {exc}") from exc

    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionRecordError(f"invalid decision record JSON: {exc}") from exc

    return verify_decision_record(record, expected_sha256=expected_sha256)


def decision_parent_ref(record: dict[str, Any]) -> dict[str, Any]:
    """Return the minimal immutable linkage for a later attempt."""
    trusted = verify_decision_record(record)
    return {
        "event_id": trusted["event_id"],
        "record_sha256": trusted["record_sha256"],
        "run_attempt": int(trusted["subject"]["run_attempt"]),
    }
