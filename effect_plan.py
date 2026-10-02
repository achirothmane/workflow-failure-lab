"""Canonical pre-effect execution plan for deferred CI retry mutation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


EFFECT_PLAN_SCHEMA = "ci-retry-gate.effect-plan.v1"


class EffectPlanError(ValueError):
    """Raised when a deferred effect plan cannot be trusted."""


def canonical_effect_plan_bytes(plan: dict[str, Any]) -> bytes:
    return json.dumps(
        plan,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def effect_plan_sha256(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_effect_plan_bytes(plan)).hexdigest()


def build_effect_plan(
    *,
    mutation_admitted: bool,
    repository: str,
    run_id: int,
    evidence_decision: dict[str, Any],
    failed_jobs: list[dict[str, Any]],
    decision_record_sha256: str,
) -> dict[str, Any]:
    scope = evidence_decision.get("scope")
    if not isinstance(scope, dict):
        raise EffectPlanError("evidence decision scope must be an object")

    failed_snapshot = sorted(
        [
            {
                "id": int(job.get("id") or 0),
                "conclusion": str(job.get("conclusion") or "").lower(),
            }
            for job in failed_jobs
            if str(job.get("conclusion") or "").lower() in {"failure", "timed_out"}
        ],
        key=lambda item: (item["id"], item["conclusion"]),
    )

    return {
        "schema_version": EFFECT_PLAN_SCHEMA,
        "mutation_admitted": bool(mutation_admitted),
        "repository": str(repository),
        "run_id": int(run_id),
        "scope": {
            "repository": str(scope.get("repository") or ""),
            "run_id": int(scope.get("run_id") or 0),
            "run_attempt": int(scope.get("run_attempt") or 0),
            "head_sha": str(scope.get("head_sha") or ""),
            "workflow_id": scope.get("workflow_id"),
        },
        "failed_jobs": failed_snapshot,
        "decision_record_sha256": str(decision_record_sha256).lower(),
    }


def write_effect_plan(path: str | Path, plan: dict[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_effect_plan_bytes(plan)
    digest = hashlib.sha256(payload).hexdigest()
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return digest


def read_effect_plan(
    path: str | Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise EffectPlanError(f"could not read effect plan: {exc}") from exc

    try:
        plan = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EffectPlanError(f"invalid effect plan JSON: {exc}") from exc

    if not isinstance(plan, dict):
        raise EffectPlanError("effect plan root must be an object")
    if plan.get("schema_version") != EFFECT_PLAN_SCHEMA:
        raise EffectPlanError(
            f"unsupported schema_version={plan.get('schema_version')!r}"
        )

    actual = effect_plan_sha256(plan)
    expected = expected_sha256.strip().lower()
    if not expected or actual != expected:
        raise EffectPlanError(
            f"effect plan SHA-256 mismatch: expected {expected or '<empty>'}, observed {actual}"
        )

    if not isinstance(plan.get("mutation_admitted"), bool):
        raise EffectPlanError("mutation_admitted must be boolean")
    if not str(plan.get("repository") or "").strip():
        raise EffectPlanError("repository is required")
    try:
        if int(plan.get("run_id")) < 1:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise EffectPlanError("run_id must be positive") from exc

    scope = plan.get("scope")
    if not isinstance(scope, dict):
        raise EffectPlanError("scope must be an object")
    failed_jobs = plan.get("failed_jobs")
    if not isinstance(failed_jobs, list):
        raise EffectPlanError("failed_jobs must be an array")

    digest = str(plan.get("decision_record_sha256") or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise EffectPlanError("decision_record_sha256 must be a SHA-256 hex digest")

    return plan
