from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "eba.integration/v0.1"
TEMPORAL_PROFILE_VERSION = "eba.temporal/v1"
CONTEXT_PROFILE_VERSION = "eba.context/v1"
CANONICAL_PROFILE_VERSION = "eba.canonical-json/v1"
MAX_SAFE_INTEGER = 9007199254740991
CI_AUDIENCE = "workflow-failure-lab/ci-retry-gate"
DECISION_KIND = "Decision"
RECEIPT_KIND = "ExecutionReceipt"
ASSUMPTION_KIND = "AssumptionState"
AUTHORITY_KIND = "AuthorityGrant"


class ContractViolation(RuntimeError):
    """Raised when an execution boundary does not satisfy the EBA contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, *, field: str, allow_none: bool = False) -> datetime | None:
    if value is None:
        if allow_none:
            return None
        raise ContractViolation(f"{field.upper()}_MISSING")
    if not isinstance(value, str) or not value:
        raise ContractViolation(f"{field.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractViolation(f"{field.upper()}_INVALID") from exc
    if parsed.tzinfo is None:
        raise ContractViolation(f"{field.upper()}_INVALID")
    return parsed.astimezone(timezone.utc)


def _validate_canonical_value(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if any(0xD800 <= ord(ch) <= 0xDFFF for ch in value):
            raise ContractViolation(f"CANONICAL_STRING_INVALID:{path}")
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ContractViolation(f"CANONICAL_INTEGER_OUT_OF_RANGE:{path}")
        return
    if isinstance(value, float):
        raise ContractViolation(f"CANONICAL_NON_INTEGER_NUMBER:{path}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractViolation(f"CANONICAL_OBJECT_KEY_INVALID:{path}")
            _validate_canonical_value(key, path=f"{path}.<key>")
            _validate_canonical_value(item, path=f"{path}.{key}")
        return
    raise ContractViolation(f"CANONICAL_TYPE_UNSUPPORTED:{path}")


def _canonical_string(value: str) -> str:
    _validate_canonical_value(value)
    rendered = json.dumps(value, ensure_ascii=False)
    return (
        rendered
        .replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


def _canonical_text(value: Any) -> str:
    _validate_canonical_value(value)
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _canonical_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_canonical_text(item) for item in value) + "]"
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            parts.append(_canonical_string(key) + ":" + _canonical_text(value[key]))
        return "{" + ",".join(parts) + "}"
    raise ContractViolation("CANONICAL_TYPE_UNSUPPORTED")


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    if not isinstance(value, dict):
        raise ContractViolation("CANONICAL_ROOT_MUST_BE_OBJECT")
    return _canonical_text(value).encode("utf-8")


def strict_json_loads(raw: str | bytes | bytearray) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ContractViolation(f"CANONICAL_DUPLICATE_KEY:{key}")
            out[key] = value
        return out

    def parse_int(token: str) -> int:
        if token == "-0":
            raise ContractViolation("CANONICAL_NEGATIVE_ZERO")
        value = int(token, 10)
        if abs(value) > MAX_SAFE_INTEGER:
            raise ContractViolation("CANONICAL_INTEGER_OUT_OF_RANGE")
        return value

    def reject_number(token: str) -> Any:
        raise ContractViolation(f"CANONICAL_NON_INTEGER_NUMBER:{token}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=object_pairs,
            parse_int=parse_int,
            parse_float=reject_number,
            parse_constant=reject_number,
        )
    except ContractViolation:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ContractViolation("CANONICAL_JSON_INVALID") from exc
    _validate_canonical_value(value)
    return value


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _with_integrity(value: dict[str, Any]) -> dict[str, Any]:
    artifact = dict(value)
    artifact.pop("integrity", None)
    digest = _digest(artifact)
    artifact["integrity"] = {"algorithm": "sha256", "digest": digest}
    return artifact


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    return f"{prefix}_{_digest(value)[:24]}"


def action_digest(request: dict[str, Any]) -> str:
    """Bind authorization to the exact principal, action and execution context."""
    bound = {
        "contract_version": request.get("contract_version"),
        "principal": request.get("principal"),
        "action": request.get("action"),
        "context": request.get("context"),
    }
    return _digest(bound)


def build_ci_action_request(
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
    head_sha: str,
    workflow_id: object,
    created_at: str | None = None,
) -> dict[str, Any]:
    timestamp = created_at or _utc_now()
    scope = {
        "repository": repository,
        "namespace": f"github-repository:{repository}",
        "run_id": int(run_id),
        "run_attempt": int(run_attempt),
        "head_sha": str(head_sha or ""),
        "workflow_id": workflow_id,
    }
    trace_seed = {"profile": "ci-retry-gate", **scope}
    trace_id = _stable_id("tr", trace_seed)

    request: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": "ActionRequest",
        "canonical_profile": CANONICAL_PROFILE_VERSION,
        "trace_id": trace_id,
        "producer": "workflow-failure-lab/ci-retry-gate",
        "audience": CI_AUDIENCE,
        "created_at": timestamp,
        "principal": {
            "type": "github_action",
            "id": "ci-retry-gate",
        },
        "action": {
            "tool": "github-actions",
            "verb": "rerun_failed_jobs",
            "resource": f"github://{repository}/actions/runs/{int(run_id)}",
            "environment": "ci",
            "side_effect": True,
        },
        "context": scope,
    }
    request["id"] = _stable_id("req", request)
    return _with_integrity(request)


_REASON_PREFIX = re.compile(r"^([A-Z][A-Z0-9_]+):")


def _block_reason_code(reason: str) -> str:
    match = _REASON_PREFIX.match(reason.strip())
    if match:
        return match.group(1)
    return "CI_RETRY_EVIDENCE_BLOCK"


def _validate_assumption_state(
    artifact: dict[str, Any],
    action_request: dict[str, Any],
    *,
    now: str,
    expected_evidence_ref: str | None = None,
) -> None:
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("ASSUMPTION_CONTRACT_VERSION_INVALID")
    if artifact.get("kind") != ASSUMPTION_KIND:
        raise ContractViolation("ASSUMPTION_KIND_INVALID")
    if artifact.get("status") != "VALID":
        raise ContractViolation(f"ASSUMPTION_NOT_VALID:{artifact.get('status')!r}")
    if artifact.get("temporal_profile") not in {None, TEMPORAL_PROFILE_VERSION}:
        raise ContractViolation("ASSUMPTION_TEMPORAL_PROFILE_INVALID")
    if artifact.get("context_profile") != CONTEXT_PROFILE_VERSION:
        raise ContractViolation("ASSUMPTION_CONTEXT_PROFILE_INVALID")
    if artifact.get("canonical_profile") != CANONICAL_PROFILE_VERSION:
        raise ContractViolation("ASSUMPTION_CANONICAL_PROFILE_INVALID")
    if artifact.get("trace_id") != action_request.get("trace_id"):
        raise ContractViolation("ASSUMPTION_TRACE_MISMATCH")
    if artifact.get("subject_ref") != action_request.get("id"):
        raise ContractViolation("ASSUMPTION_SUBJECT_MISMATCH")
    if artifact.get("action_digest") != action_digest(action_request):
        raise ContractViolation("ASSUMPTION_ACTION_MISMATCH")
    context = action_request.get("context")
    if not isinstance(context, dict):
        raise ContractViolation("ASSUMPTION_CONTEXT_INVALID")
    trust = artifact.get("trust")
    if not isinstance(trust, dict):
        raise ContractViolation("ASSUMPTION_TRUST_ENVELOPE_MISSING")
    if trust.get("mode") != "trusted_in_process":
        raise ContractViolation("ASSUMPTION_TRUST_MODE_INVALID")
    if artifact.get("producer") != "assumption-gate/ci-retry-profile":
        raise ContractViolation("ASSUMPTION_PRODUCER_MISMATCH")
    if trust.get("issuer") != artifact.get("producer"):
        raise ContractViolation("ASSUMPTION_ISSUER_MISMATCH")
    if trust.get("audience") != action_request.get("audience"):
        raise ContractViolation("ASSUMPTION_AUDIENCE_MISMATCH")
    if trust.get("namespace") != context.get("namespace"):
        raise ContractViolation("ASSUMPTION_NAMESPACE_MISMATCH")
    if expected_evidence_ref is not None:
        refs = artifact.get("evidence_refs")
        if not isinstance(refs, list) or refs != [expected_evidence_ref]:
            raise ContractViolation("ASSUMPTION_EVIDENCE_BINDING_MISMATCH")

    current = _parse_timestamp(now, field="evaluation_time")
    checked_at = _parse_timestamp(artifact.get("checked_at"), field="assumption_checked_at")
    assert current is not None and checked_at is not None
    if checked_at > current:
        raise ContractViolation("ASSUMPTION_CHECKED_AT_FUTURE")

    if "valid_until" not in artifact:
        raise ContractViolation("ASSUMPTION_VALID_UNTIL_MISSING")
    valid_until = _parse_timestamp(
        artifact.get("valid_until"),
        field="assumption_valid_until",
        allow_none=True,
    )
    if valid_until is not None and current >= valid_until:
        raise ContractViolation("ASSUMPTION_STALE")

    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ContractViolation("ASSUMPTION_INTEGRITY_INVALID")
    expected = integrity.get("digest")
    unsigned = dict(artifact)
    unsigned.pop("integrity", None)
    if expected != _digest(unsigned):
        raise ContractViolation("ASSUMPTION_INTEGRITY_INVALID")

def _authority_scope_digest(action_request: dict[str, Any]) -> str:
    principal = action_request.get("principal")
    action = action_request.get("action")
    if not isinstance(principal, dict) or not isinstance(action, dict):
        raise ContractViolation("AUTHORITY_REQUEST_INVALID")
    return _digest(
        {
            "actor": principal.get("id"),
            "tool": action.get("tool"),
            "operation": action.get("verb"),
            "resource": action.get("resource"),
            "side_effect": action.get("side_effect"),
        }
    )


def _validate_authority_grant(
    artifact: dict[str, Any],
    action_request: dict[str, Any],
    *,
    now: str,
) -> None:
    if artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("AUTHORITY_CONTRACT_VERSION_INVALID")
    if artifact.get("kind") != AUTHORITY_KIND:
        raise ContractViolation("AUTHORITY_KIND_INVALID")
    if artifact.get("revoked") is not False:
        raise ContractViolation("AUTHORITY_REVOKED")
    if artifact.get("temporal_profile") not in {None, TEMPORAL_PROFILE_VERSION}:
        raise ContractViolation("AUTHORITY_TEMPORAL_PROFILE_INVALID")
    if artifact.get("context_profile") != CONTEXT_PROFILE_VERSION:
        raise ContractViolation("AUTHORITY_CONTEXT_PROFILE_INVALID")
    if artifact.get("canonical_profile") != CANONICAL_PROFILE_VERSION:
        raise ContractViolation("AUTHORITY_CANONICAL_PROFILE_INVALID")
    if artifact.get("trace_id") != action_request.get("trace_id"):
        raise ContractViolation("AUTHORITY_TRACE_MISMATCH")
    context = action_request.get("context")
    if not isinstance(context, dict):
        raise ContractViolation("AUTHORITY_REQUEST_INVALID")
    trust = artifact.get("trust")
    if not isinstance(trust, dict):
        raise ContractViolation("AUTHORITY_TRUST_ENVELOPE_MISSING")
    if trust.get("mode") != "trusted_in_process":
        raise ContractViolation("AUTHORITY_TRUST_MODE_INVALID")
    if artifact.get("producer") != "agent-action-guard/ci-retry-profile":
        raise ContractViolation("AUTHORITY_PRODUCER_MISMATCH")
    if trust.get("issuer") != artifact.get("issued_by"):
        raise ContractViolation("AUTHORITY_ISSUER_MISMATCH")
    if trust.get("audience") != action_request.get("audience"):
        raise ContractViolation("AUTHORITY_AUDIENCE_MISMATCH")
    if trust.get("namespace") != context.get("namespace"):
        raise ContractViolation("AUTHORITY_NAMESPACE_MISMATCH")
    if artifact.get("subject_ref") != action_request.get("id"):
        raise ContractViolation("AUTHORITY_SUBJECT_MISMATCH")

    current = _parse_timestamp(now, field="evaluation_time")
    not_before = _parse_timestamp(
        artifact.get("not_before"),
        field="authority_not_before",
    )
    expires_at = _parse_timestamp(
        artifact.get("expires_at"),
        field="authority_expires_at",
    )
    assert current is not None and not_before is not None and expires_at is not None
    if expires_at <= not_before:
        raise ContractViolation("AUTHORITY_WINDOW_INVALID")
    if current < not_before:
        raise ContractViolation("AUTHORITY_NOT_YET_VALID")
    if current >= expires_at:
        raise ContractViolation("AUTHORITY_EXPIRED")

    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ContractViolation("AUTHORITY_INTEGRITY_INVALID")
    unsigned = dict(artifact)
    unsigned.pop("integrity", None)
    if integrity.get("digest") != _digest(unsigned):
        raise ContractViolation("AUTHORITY_INTEGRITY_INVALID")

    principal = action_request.get("principal")
    action = action_request.get("action")
    if not isinstance(principal, dict) or not isinstance(action, dict):
        raise ContractViolation("AUTHORITY_REQUEST_INVALID")

    grant_principal = artifact.get("principal")
    if not isinstance(grant_principal, dict) or grant_principal.get("id") != principal.get("id"):
        raise ContractViolation("AUTHORITY_PRINCIPAL_MISMATCH")

    if artifact.get("action_id") != action_request.get("id"):
        raise ContractViolation("AUTHORITY_ACTION_ID_MISMATCH")
    if artifact.get("action_scope_digest") != _authority_scope_digest(action_request):
        raise ContractViolation("AUTHORITY_SCOPE_MISMATCH")

    resource_scope = artifact.get("resource_scope")
    if not isinstance(resource_scope, list) or action.get("resource") not in resource_scope:
        raise ContractViolation("AUTHORITY_RESOURCE_MISMATCH")

    allowed = artifact.get("allowed_actions")
    if not isinstance(allowed, list):
        raise ContractViolation("AUTHORITY_ACTIONS_INVALID")
    expected_action = {
        "tool": action.get("tool"),
        "operation": action.get("verb"),
        "side_effect": action.get("side_effect"),
    }
    if expected_action not in allowed:
        raise ContractViolation("AUTHORITY_OPERATION_MISMATCH")

    constraints = artifact.get("context_constraints")
    if isinstance(constraints, dict):
        environments = constraints.get("environment")
        if environments is not None:
            if not isinstance(environments, list) or action.get("environment") not in environments:
                raise ContractViolation("AUTHORITY_CONTEXT_MISMATCH")


def build_decision_artifact(
    *,
    action_request: dict[str, Any],
    evidence_decision: dict[str, Any],
    evidence_sha256: str,
    assumption_states: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    authority_grant: dict[str, Any] | None = None,
    require_authority: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    validation_time = created_at or _utc_now()
    _parse_timestamp(validation_time, field="decision_created_at")
    decision = str(evidence_decision.get("decision") or "")
    if decision not in {"ALLOW", "BLOCK"}:
        raise ContractViolation(f"unsupported decision: {decision!r}")

    reasons = evidence_decision.get("reasons")
    reason = str(reasons[0]) if isinstance(reasons, list) and reasons else "No gate reason supplied."

    scope = evidence_decision.get("scope")
    context = action_request.get("context")
    if decision == "ALLOW":
        if not isinstance(scope, dict) or not isinstance(context, dict):
            decision = "BLOCK"
            reason = "CONTEXT_MISMATCH: decision scope or action context is missing."
        else:
            scope_fields = ("repository", "run_id", "run_attempt", "head_sha", "workflow_id")
            mismatches = [
                field
                for field in scope_fields
                if scope.get(field) != context.get(field)
            ]
            if mismatches:
                decision = "BLOCK"
                reason = "CONTEXT_MISMATCH: " + ", ".join(mismatches) + "."

    if decision == "ALLOW":
        try:
            for assumption_state in assumption_states:
                _validate_assumption_state(
                    assumption_state,
                    action_request,
                    now=validation_time,
                    expected_evidence_ref=f"sha256:{evidence_sha256}",
                )
        except ContractViolation as exc:
            decision = "BLOCK"
            reason = f"ASSUMPTION_INVALID: {exc}."

    if decision == "ALLOW" and require_authority and authority_grant is None:
        decision = "BLOCK"
        reason = "AUTHORITY_MISSING: required AuthorityGrant was not supplied."

    if decision == "ALLOW" and authority_grant is not None:
        try:
            _validate_authority_grant(authority_grant, action_request, now=validation_time)
        except ContractViolation as exc:
            decision = "BLOCK"
            reason = f"AUTHORITY_INVALID: {exc}."

    timestamp = validation_time

    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": DECISION_KIND,
        "canonical_profile": CANONICAL_PROFILE_VERSION,
        "trace_id": action_request.get("trace_id"),
        "producer": "workflow-failure-lab/ci-retry-gate",
        "created_at": timestamp,
        "request_ref": action_request.get("id"),
        "decision": decision,
        "policy_version": str(
            evidence_decision.get("schema_version") or "ci-retry-gate.evidence-decision.v1"
        ),
        "basis": {
            "evidence_refs": [f"sha256:{evidence_sha256}"],
            "assumption_refs": [
                str(item.get("id"))
                for item in assumption_states
                if item.get("id")
            ],
            "authority_ref": (
                str(authority_grant.get("id"))
                if isinstance(authority_grant, dict) and authority_grant.get("id")
                else None
            ),
            "budget_ref": None,
            "approval_refs": [],
        },
        "reason_codes": [
            "ALL_REQUIRED_GATES_SATISFIED" if decision == "ALLOW" else _block_reason_code(reason)
        ],
        "reasons": [reason],
        "valid_until": evidence_decision.get("fresh_until"),
        "action_digest": action_digest(action_request),
        "profile": {
            "name": "ci-retry-gate",
            "evidence_status": evidence_decision.get("evidence_status"),
            "confidence": evidence_decision.get("confidence"),
            "scope": evidence_decision.get("scope"),
        },
    }
    artifact["id"] = _stable_id("dec", artifact)
    return _with_integrity(artifact)


def ensure_decision_allows_request(
    decision_artifact: dict[str, Any],
    action_request: dict[str, Any],
    *,
    now: str,
    assumption_states: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    authority_grant: dict[str, Any] | None = None,
) -> None:
    """Fail closed unless the Decision authorizes this exact ActionRequest."""
    if decision_artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("unsupported integration contract version")
    if decision_artifact.get("kind") != DECISION_KIND:
        raise ContractViolation("execution requires a Decision artifact")
    if decision_artifact.get("canonical_profile") != CANONICAL_PROFILE_VERSION:
        raise ContractViolation("DECISION_CANONICAL_PROFILE_INVALID")
    if action_request.get("canonical_profile") != CANONICAL_PROFILE_VERSION:
        raise ContractViolation("ACTION_CANONICAL_PROFILE_INVALID")
    if decision_artifact.get("decision") != "ALLOW":
        raise ContractViolation("execution requires ALLOW")
    if decision_artifact.get("request_ref") != action_request.get("id"):
        raise ContractViolation("decision/request reference mismatch")
    expected = action_digest(action_request)
    if decision_artifact.get("action_digest") != expected:
        raise ContractViolation("ACTION_MUTATED_AFTER_DECISION")

    current = _parse_timestamp(now, field="evaluation_time")
    assert current is not None
    if "valid_until" not in decision_artifact:
        raise ContractViolation("DECISION_VALID_UNTIL_MISSING")
    valid_until = _parse_timestamp(
        decision_artifact.get("valid_until"),
        field="decision_valid_until",
        allow_none=True,
    )
    if valid_until is not None and current >= valid_until:
        raise ContractViolation("DECISION_EXPIRED")

    basis = decision_artifact.get("basis")
    if not isinstance(basis, dict):
        raise ContractViolation("decision basis is missing")
    required_refs = [str(item) for item in basis.get("assumption_refs") or []]
    supplied = {
        str(item.get("id")): item
        for item in assumption_states
        if item.get("id")
    }
    missing = [ref for ref in required_refs if ref not in supplied]
    if missing:
        raise ContractViolation("ASSUMPTION_REFERENCE_MISSING")
    for ref in required_refs:
        evidence_refs = basis.get("evidence_refs") or []
        expected_evidence_ref = str(evidence_refs[0]) if len(evidence_refs) == 1 else None
        _validate_assumption_state(
            supplied[ref],
            action_request,
            now=now,
            expected_evidence_ref=expected_evidence_ref,
        )

    authority_ref = basis.get("authority_ref")
    if authority_ref is not None:
        if authority_grant is None:
            raise ContractViolation("AUTHORITY_REFERENCE_MISSING")
        if str(authority_grant.get("id")) != str(authority_ref):
            raise ContractViolation("AUTHORITY_REFERENCE_MISMATCH")
        _validate_authority_grant(authority_grant, action_request, now=now)


def build_execution_receipt(
    *,
    action_request: dict[str, Any],
    decision_artifact: dict[str, Any],
    rerun_triggered: bool,
    assumption_states: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    authority_grant: dict[str, Any] | None = None,
    created_at: str | None = None,
    admitted_at: str | None = None,
    execution_reason: str | None = None,
    execution_outcome: str | None = None,
) -> dict[str, Any]:
    timestamp = created_at or _utc_now()
    outcome = execution_outcome or ("SUCCEEDED" if rerun_triggered else "NOT_EXECUTED")
    if outcome not in {"SUCCEEDED", "NOT_EXECUTED", "UNKNOWN"}:
        raise ContractViolation("EXECUTION_RECEIPT_OUTCOME_INVALID")
    if rerun_triggered and outcome != "SUCCEEDED":
        raise ContractViolation("EXECUTION_RECEIPT_TRIGGER_OUTCOME_MISMATCH")
    if rerun_triggered:
        boundary_time = admitted_at or timestamp
        ensure_decision_allows_request(
            decision_artifact,
            action_request,
            now=boundary_time,
            assumption_states=assumption_states,
            authority_grant=authority_grant,
        )

    receipt: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": RECEIPT_KIND,
        "canonical_profile": CANONICAL_PROFILE_VERSION,
        "trace_id": action_request.get("trace_id"),
        "producer": "workflow-failure-lab/ci-retry-gate",
        "created_at": timestamp,
        "request_ref": action_request.get("id"),
        "decision_ref": decision_artifact.get("id"),
        "action_digest": action_digest(action_request),
        "admitted_at": admitted_at if outcome in {"SUCCEEDED", "UNKNOWN"} else None,
        "started_at": timestamp,
        "finished_at": timestamp,
        "outcome": outcome,
        "status_reason": execution_reason,
        "resource_changes": (
            [
                {
                    "resource": action_request.get("action", {}).get("resource"),
                    "operation": "rerun_failed_jobs",
                    "result": (
                        "dispatch-accepted"
                        if outcome == "SUCCEEDED"
                        else "dispatch-unknown"
                    ),
                }
            ]
            if outcome in {"SUCCEEDED", "UNKNOWN"}
            else []
        ),
        "actual_usage": {},
        "produced_evidence_refs": [],
    }
    receipt["id"] = _stable_id("receipt", receipt)
    return _with_integrity(receipt)


def write_contract_artifact(path: str | Path, artifact: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json_bytes(artifact)
    digest = hashlib.sha256(payload).hexdigest()
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return digest


def verify_contract_artifact(
    artifact: object,
    *,
    expected_sha256: str | None = None,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    """Verify canonical shape, embedded integrity, and optional external digest."""
    if not isinstance(artifact, dict):
        raise ContractViolation("CONTRACT_ARTIFACT_ROOT_INVALID")
    _validate_canonical_value(artifact)

    if expected_kind is not None and artifact.get("kind") != expected_kind:
        raise ContractViolation("CONTRACT_ARTIFACT_KIND_MISMATCH")

    integrity = artifact.get("integrity")
    if not isinstance(integrity, dict):
        raise ContractViolation("CONTRACT_ARTIFACT_INTEGRITY_MISSING")
    if integrity.get("algorithm") != "sha256":
        raise ContractViolation("CONTRACT_ARTIFACT_INTEGRITY_ALGORITHM_INVALID")

    embedded = str(integrity.get("digest") or "").strip().lower()
    if len(embedded) != 64 or any(ch not in "0123456789abcdef" for ch in embedded):
        raise ContractViolation("CONTRACT_ARTIFACT_INTEGRITY_DIGEST_INVALID")

    semantic = dict(artifact)
    semantic.pop("integrity", None)
    actual_semantic = hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()
    if actual_semantic != embedded:
        raise ContractViolation("CONTRACT_ARTIFACT_INTEGRITY_MISMATCH")

    if expected_sha256 is not None:
        expected = expected_sha256.strip().lower()
        actual_external = hashlib.sha256(canonical_json_bytes(artifact)).hexdigest()
        if not expected or actual_external != expected:
            raise ContractViolation("CONTRACT_ARTIFACT_EXTERNAL_DIGEST_MISMATCH")

    return artifact


def read_contract_artifact(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_kind: str | None = None,
) -> dict[str, Any]:
    """Read strict canonical JSON and verify it before effect-boundary use."""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise ContractViolation("CONTRACT_ARTIFACT_READ_FAILED") from exc

    artifact = strict_json_loads(raw)
    return verify_contract_artifact(
        artifact,
        expected_sha256=expected_sha256,
        expected_kind=expected_kind,
    )
