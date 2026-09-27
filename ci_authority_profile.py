from __future__ import annotations

import hashlib
from typing import Any

from eba_integration_contract import CONTRACT_VERSION, canonical_json_bytes

POLICY_ID = "ci-retry-gate-runtime-authority-v1"
ALLOW_RULE_ID = "allow-ci-retry-rerun-failed-jobs"


class AuthorityProfileError(ValueError):
    pass


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


def _mapped_action(action_request: dict[str, Any]) -> dict[str, Any]:
    principal = action_request.get("principal")
    action = action_request.get("action")
    context = action_request.get("context")
    if not isinstance(principal, dict) or not isinstance(action, dict) or not isinstance(context, dict):
        raise AuthorityProfileError("ACTION_REQUEST_INVALID")

    actor = principal.get("id")
    verb = action.get("verb")
    resource = action.get("resource")
    environment = action.get("environment")
    repository = context.get("repository")
    run_id = context.get("run_id")

    expected_resource = f"github://{repository}/actions/runs/{run_id}"
    if actor != "ci-retry-gate":
        raise AuthorityProfileError("AUTHORITY_PRINCIPAL_MISMATCH")
    if verb != "rerun_failed_jobs":
        raise AuthorityProfileError("AUTHORITY_OPERATION_MISMATCH")
    if environment != "ci":
        raise AuthorityProfileError("AUTHORITY_CONTEXT_MISMATCH")
    if resource != expected_resource:
        raise AuthorityProfileError("AUTHORITY_RESOURCE_MISMATCH")

    return {
        "actor": actor,
        "tool": "github-actions",
        "operation": verb,
        "resource": resource,
        "side_effect": True,
    }


def authority_scope_digest(action_request: dict[str, Any]) -> str:
    return _digest(_mapped_action(action_request))


def build_ci_authority_grant(
    *,
    action_request: dict[str, Any],
    created_at: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Apply the precompiled Agent Action Guard CI retry authority profile.

    Normative policy shape:
      ALLOW when actor == ci-retry-gate,
                 tool == github-actions,
                 operation == rerun_failed_jobs,
                 side_effect == true.
    Resource is unconstrained by the policy rule, then narrowed in the grant to
    the exact resource requested. Structural checks bind that resource to
    repository/run_id in the ActionRequest.
    """
    mapped = _mapped_action(action_request)

    grant: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": "AuthorityGrant",
        "trace_id": action_request.get("trace_id"),
        "producer": "agent-action-guard/ci-retry-profile",
        "created_at": created_at,
        "principal": {
            "type": "agent",
            "id": mapped["actor"],
        },
        "allowed_actions": [
            {
                "tool": mapped["tool"],
                "operation": mapped["operation"],
                "side_effect": mapped["side_effect"],
            }
        ],
        "resource_scope": [mapped["resource"]],
        "context_constraints": {
            "environment": ["ci"],
        },
        "issued_by": f"policy:{POLICY_ID}",
        "not_before": created_at,
        "expires_at": expires_at,
        "revoked": False,
        "policy_ref": POLICY_ID,
        "matched_allow_rule_ids": [ALLOW_RULE_ID],
        "action_id": action_request.get("id"),
        "action_scope_digest": _digest(mapped),
    }
    grant["id"] = _stable_id("auth", grant)
    return _with_integrity(grant)
