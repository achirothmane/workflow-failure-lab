"""Preserve raw GitHub principals for Decision Evidence Records."""

from __future__ import annotations

from typing import Any


def github_actor_identity(actor: object) -> dict[str, str] | None:
    if not isinstance(actor, dict):
        return None

    raw = str(actor.get("login") or "").strip()
    if not raw:
        return None

    actor_type = str(actor.get("type") or "").strip().lower()
    if actor_type == "user":
        identity_type = "human"
    elif actor_type == "bot":
        identity_type = "bot"
    elif actor_type == "app":
        identity_type = "github_app"
    else:
        identity_type = "unknown"

    return {
        "raw": raw,
        "identity_type": identity_type,
    }


def action_engine_identity() -> dict[str, str]:
    # A composite Action is software, not itself a GitHub App principal.
    # Preserve the raw engine identity without pretending to know its auth type.
    return {
        "raw": "achirothmane/workflow-failure-lab",
        "identity_type": "unknown",
    }


def token_identity(raw: str = "github-token") -> dict[str, str]:
    return {
        "raw": raw,
        "identity_type": "token",
    }


def collect_decision_identities(
    run: dict[str, Any],
    *,
    rerun_will_be_requested: bool,
) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {
        "decision_engine": action_engine_identity(),
    }

    workflow_actor = github_actor_identity(run.get("actor"))
    if workflow_actor is not None:
        identities["workflow_actor"] = workflow_actor

    triggering_actor = github_actor_identity(run.get("triggering_actor"))
    if triggering_actor is not None:
        identities["workflow_triggering_actor"] = triggering_actor

    if rerun_will_be_requested:
        identities["rerun_initiator"] = token_identity()

    return identities
