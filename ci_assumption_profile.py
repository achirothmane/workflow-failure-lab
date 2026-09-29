from __future__ import annotations

import hashlib
from typing import Any

from eba_integration_contract import (
    CI_AUDIENCE,
    CANONICAL_PROFILE_VERSION,
    CONTEXT_PROFILE_VERSION,
    CONTRACT_VERSION,
    TEMPORAL_PROFILE_VERSION,
    action_digest,
    canonical_json_bytes,
)

ASSUMPTION_ID = "ci.retry.failure-is-transient-and-rerunnable"
ASSUMPTION_PROPOSITION = (
    "The failed CI job set bound to this ActionRequest is transient, causally supported, "
    "side-effect-safe, and safe to rerun under the current evidence scope."
)


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stable_id(prefix: str, value: dict[str, Any]) -> str:
    return f"{prefix}_{_digest(value)[:24]}"


def _with_integrity(value: dict[str, Any]) -> dict[str, Any]:
    artifact = dict(value)
    artifact.pop("integrity", None)
    artifact["integrity"] = {
        "algorithm": "sha256",
        "digest": _digest(artifact),
    }
    return artifact


def build_ci_retry_assumption_state(
    *,
    action_request: dict[str, Any],
    evidence_decision: dict[str, Any],
    evidence_sha256: str,
    created_at: str,
) -> dict[str, Any]:
    """Project CI Retry Gate evidence into the AssumptionState contract.

    This is a profile adapter, not a second retry policy. The isolated evidence
    gate remains the source of the causal/transient determination. This adapter
    makes that assumption explicit and consumable by the EBA integration layer.
    """
    evidence_status = str(evidence_decision.get("evidence_status") or "UNKNOWN")
    evidence_gate_decision = str(evidence_decision.get("decision") or "BLOCK")

    if evidence_gate_decision == "ALLOW" and evidence_status == "SUFFICIENT":
        status = "VALID"
        invalidation_reasons: list[str] = []
    elif evidence_status == "CONTRADICTED":
        status = "CONTRADICTED"
        contradictions = evidence_decision.get("contradictions")
        invalidation_reasons = (
            [str(item) for item in contradictions]
            if isinstance(contradictions, list) and contradictions
            else ["EVIDENCE_CONTRADICTED"]
        )
    else:
        status = "UNKNOWN"
        reasons = evidence_decision.get("reasons")
        invalidation_reasons = (
            [str(item) for item in reasons]
            if isinstance(reasons, list) and reasons
            else ["EVIDENCE_INSUFFICIENT"]
        )

    artifact: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": "AssumptionState",
        "temporal_profile": TEMPORAL_PROFILE_VERSION,
        "context_profile": CONTEXT_PROFILE_VERSION,
        "canonical_profile": CANONICAL_PROFILE_VERSION,
        "trace_id": action_request.get("trace_id"),
        "subject_ref": action_request.get("id"),
        "action_digest": action_digest(action_request),
        "producer": "assumption-gate/ci-retry-profile",
        "trust": {
            "mode": "trusted_in_process",
            "issuer": "assumption-gate/ci-retry-profile",
            "audience": action_request.get("audience"),
            "namespace": action_request.get("context", {}).get("namespace"),
        },
        "created_at": created_at,
        "assumption_id": ASSUMPTION_ID,
        "proposition": ASSUMPTION_PROPOSITION,
        "status": status,
        "evidence_refs": [f"sha256:{evidence_sha256}"],
        "dependencies": [
            "repository",
            "run-id",
            "run-attempt",
            "head-sha",
            "workflow-id",
            "failed-job-set",
        ],
        "checked_at": created_at,
        "valid_until": evidence_decision.get("fresh_until"),
        "invalidation_reasons": invalidation_reasons,
        "profile": {
            "source_decision_schema": evidence_decision.get("schema_version"),
            "source_evidence_status": evidence_status,
            "scope": evidence_decision.get("scope"),
        },
    }
    artifact["id"] = _stable_id("as", artifact)
    return _with_integrity(artifact)
