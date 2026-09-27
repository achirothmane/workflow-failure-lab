from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "eba.integration/v0.1"
DECISION_KIND = "Decision"
RECEIPT_KIND = "ExecutionReceipt"


class ContractViolation(RuntimeError):
    """Raised when an execution boundary does not satisfy the EBA contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


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
        "trace_id": trace_id,
        "producer": "workflow-failure-lab/ci-retry-gate",
        "created_at": timestamp,
        "principal": {
            "type": "github_action",
            "id": "ci-retry-gate",
        },
        "action": {
            "verb": "rerun_failed_jobs",
            "resource": f"github://{repository}/actions/runs/{int(run_id)}",
            "environment": "ci",
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


def build_decision_artifact(
    *,
    action_request: dict[str, Any],
    evidence_decision: dict[str, Any],
    evidence_sha256: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    decision = str(evidence_decision.get("decision") or "")
    if decision not in {"ALLOW", "BLOCK"}:
        raise ContractViolation(f"unsupported decision: {decision!r}")

    reasons = evidence_decision.get("reasons")
    reason = str(reasons[0]) if isinstance(reasons, list) and reasons else "No gate reason supplied."
    timestamp = created_at or _utc_now()

    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": DECISION_KIND,
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
            "assumption_refs": [],
            "authority_ref": None,
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
) -> None:
    """Fail closed unless the Decision authorizes this exact ActionRequest."""
    if decision_artifact.get("contract_version") != CONTRACT_VERSION:
        raise ContractViolation("unsupported integration contract version")
    if decision_artifact.get("kind") != DECISION_KIND:
        raise ContractViolation("execution requires a Decision artifact")
    if decision_artifact.get("decision") != "ALLOW":
        raise ContractViolation("execution requires ALLOW")
    if decision_artifact.get("request_ref") != action_request.get("id"):
        raise ContractViolation("decision/request reference mismatch")
    expected = action_digest(action_request)
    if decision_artifact.get("action_digest") != expected:
        raise ContractViolation("ACTION_MUTATED_AFTER_DECISION")


def build_execution_receipt(
    *,
    action_request: dict[str, Any],
    decision_artifact: dict[str, Any],
    rerun_triggered: bool,
    created_at: str | None = None,
) -> dict[str, Any]:
    timestamp = created_at or _utc_now()
    if rerun_triggered:
        ensure_decision_allows_request(decision_artifact, action_request)

    receipt: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": RECEIPT_KIND,
        "trace_id": action_request.get("trace_id"),
        "producer": "workflow-failure-lab/ci-retry-gate",
        "created_at": timestamp,
        "request_ref": action_request.get("id"),
        "decision_ref": decision_artifact.get("id"),
        "action_digest": action_digest(action_request),
        "started_at": timestamp,
        "finished_at": timestamp,
        "outcome": "SUCCEEDED" if rerun_triggered else "NOT_EXECUTED",
        "resource_changes": (
            [
                {
                    "resource": action_request.get("action", {}).get("resource"),
                    "operation": "rerun_failed_jobs",
                    "result": "dispatch-accepted",
                }
            ]
            if rerun_triggered
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
