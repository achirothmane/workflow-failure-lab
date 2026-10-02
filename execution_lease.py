"""Durable executor ownership lease for deferred CI effects.

The lease is intentionally independent from GitHub workflow semantics. A worker may
execute an admitted EffectPlan only while it owns the highest non-conflicting lease
epoch in the durable registry snapshot supplied to the effect boundary.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


EXECUTION_LEASE_SCHEMA = "ci-retry-gate.execution-lease.v1"


class ExecutionLeaseError(ValueError):
    """Raised when execution ownership cannot be trusted."""


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ExecutionLeaseError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ExecutionLeaseError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise ExecutionLeaseError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def lease_digest(lease: dict[str, Any]) -> str:
    unsigned = dict(lease)
    unsigned.pop("integrity", None)
    return _digest(unsigned)


def seal_execution_lease(lease: dict[str, Any]) -> dict[str, Any]:
    artifact = dict(lease)
    artifact.pop("integrity", None)
    artifact["integrity"] = {
        "algorithm": "sha256",
        "digest": _digest(artifact),
    }
    return artifact


def build_execution_lease(
    *,
    owner_id: str,
    epoch: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
    repository: str,
    run_id: int,
    issued_at: str,
    ttl_seconds: int,
    previous_lease_sha256: str | None = None,
    previous_lease_set_sha256: str | None = None,
) -> dict[str, Any]:
    owner = str(owner_id).strip()
    if not owner:
        raise ExecutionLeaseError("owner_id is required")
    if int(epoch) < 1:
        raise ExecutionLeaseError("epoch must be positive")
    if int(ttl_seconds) < 1:
        raise ExecutionLeaseError("ttl_seconds must be positive")

    issued = _parse_timestamp(issued_at, field="issued_at")
    expires = issued + timedelta(seconds=int(ttl_seconds))

    for field, value in (
        ("decision_record_sha256", decision_record_sha256),
        ("effect_plan_sha256", effect_plan_sha256),
    ):
        digest = str(value).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExecutionLeaseError(f"{field} must be a SHA-256 hex digest")

    previous = None
    if previous_lease_sha256 is not None:
        previous = str(previous_lease_sha256).strip().lower()
        if len(previous) != 64 or any(ch not in "0123456789abcdef" for ch in previous):
            raise ExecutionLeaseError("previous_lease_sha256 must be a SHA-256 hex digest")

    previous_set = None
    if previous_lease_set_sha256 is not None:
        previous_set = str(previous_lease_set_sha256).strip().lower()
        if len(previous_set) != 64 or any(ch not in "0123456789abcdef" for ch in previous_set):
            raise ExecutionLeaseError(
                "previous_lease_set_sha256 must be a SHA-256 hex digest"
            )
    if previous is not None and previous_set is not None:
        raise ExecutionLeaseError(
            "execution lease cannot bind both a single predecessor and a predecessor set"
        )

    lease = {
        "schema_version": EXECUTION_LEASE_SCHEMA,
        "lease_id": f"lease_{uuid.uuid4().hex}",
        "owner_id": owner,
        "epoch": int(epoch),
        "issued_at": _iso(issued),
        "expires_at": _iso(expires),
        "repository": str(repository),
        "run_id": int(run_id),
        "decision_record_sha256": str(decision_record_sha256).lower(),
        "effect_plan_sha256": str(effect_plan_sha256).lower(),
        "previous_lease_sha256": previous,
        "previous_lease_set_sha256": previous_set,
    }
    return seal_execution_lease(lease)


def build_takeover_lease(
    *,
    previous_lease: dict[str, Any],
    owner_id: str,
    issued_at: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    verify_execution_lease(previous_lease)
    takeover_time = _parse_timestamp(issued_at, field="issued_at")
    previous_expiry = _parse_timestamp(previous_lease["expires_at"], field="expires_at")
    if takeover_time < previous_expiry:
        raise ExecutionLeaseError(
            "LEASE_STILL_ACTIVE: takeover cannot occur before previous lease expiry"
        )

    return build_execution_lease(
        owner_id=owner_id,
        epoch=int(previous_lease["epoch"]) + 1,
        decision_record_sha256=str(previous_lease["decision_record_sha256"]),
        effect_plan_sha256=str(previous_lease["effect_plan_sha256"]),
        repository=str(previous_lease["repository"]),
        run_id=int(previous_lease["run_id"]),
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
        previous_lease_sha256=lease_digest(previous_lease),
    )


def verify_execution_lease(lease: dict[str, Any]) -> None:
    if not isinstance(lease, dict):
        raise ExecutionLeaseError("lease root must be an object")
    if lease.get("schema_version") != EXECUTION_LEASE_SCHEMA:
        raise ExecutionLeaseError("unsupported execution lease schema")

    owner = str(lease.get("owner_id") or "").strip()
    if not owner:
        raise ExecutionLeaseError("owner_id is required")
    try:
        epoch = int(lease.get("epoch"))
        run_id = int(lease.get("run_id"))
    except (TypeError, ValueError) as exc:
        raise ExecutionLeaseError("epoch/run_id must be integers") from exc
    if epoch < 1 or run_id < 1:
        raise ExecutionLeaseError("epoch/run_id must be positive")

    issued = _parse_timestamp(lease.get("issued_at"), field="issued_at")
    expires = _parse_timestamp(lease.get("expires_at"), field="expires_at")
    if expires <= issued:
        raise ExecutionLeaseError("lease validity window is invalid")

    for field in ("decision_record_sha256", "effect_plan_sha256"):
        digest = str(lease.get(field) or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExecutionLeaseError(f"{field} must be a SHA-256 hex digest")

    previous = lease.get("previous_lease_sha256")
    if previous is not None:
        previous = str(previous).strip().lower()
        if len(previous) != 64 or any(ch not in "0123456789abcdef" for ch in previous):
            raise ExecutionLeaseError("previous_lease_sha256 must be a SHA-256 hex digest")

    previous_set = lease.get("previous_lease_set_sha256")
    if previous_set is not None:
        previous_set = str(previous_set).strip().lower()
        if len(previous_set) != 64 or any(ch not in "0123456789abcdef" for ch in previous_set):
            raise ExecutionLeaseError(
                "previous_lease_set_sha256 must be a SHA-256 hex digest"
            )
    if previous is not None and previous_set is not None:
        raise ExecutionLeaseError(
            "execution lease cannot bind both a single predecessor and a predecessor set"
        )

    integrity = lease.get("integrity")
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256":
        raise ExecutionLeaseError("execution lease integrity metadata is invalid")
    if integrity.get("digest") != lease_digest(lease):
        raise ExecutionLeaseError("execution lease SHA-256 mismatch")




def _lease_set_digest(leases: list[dict[str, Any]]) -> str:
    if not leases:
        raise ExecutionLeaseError("lease set is empty")
    digests = sorted(lease_digest(item) for item in leases)
    return hashlib.sha256("\n".join(digests).encode("ascii")).hexdigest()


def build_contention_resolution_lease(
    *,
    contending_leases: list[dict[str, Any]],
    owner_id: str,
    issued_at: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    if len(contending_leases) < 2:
        raise ExecutionLeaseError(
            "LEASE_CONTENTION_REQUIRED: at least two competing leases are required"
        )
    for lease in contending_leases:
        verify_execution_lease(lease)

    epochs = {int(item["epoch"]) for item in contending_leases}
    if len(epochs) != 1:
        raise ExecutionLeaseError(
            "LEASE_CONTENTION_EPOCH_MISMATCH: contenders must share one epoch"
        )

    bindings = {
        (
            str(item["decision_record_sha256"]),
            str(item["effect_plan_sha256"]),
            str(item["repository"]),
            int(item["run_id"]),
        )
        for item in contending_leases
    }
    if len(bindings) != 1:
        raise ExecutionLeaseError(
            "LEASE_CONTENTION_BINDING_MISMATCH: contenders do not govern the same effect"
        )

    unique = {lease_digest(item) for item in contending_leases}
    if len(unique) < 2:
        raise ExecutionLeaseError(
            "LEASE_CONTENTION_REQUIRED: contenders are not distinct"
        )

    resolution_time = _parse_timestamp(issued_at, field="issued_at")
    latest_expiry = max(
        _parse_timestamp(item["expires_at"], field="expires_at")
        for item in contending_leases
    )
    if resolution_time < latest_expiry:
        raise ExecutionLeaseError(
            "LEASE_CONTENTION_ACTIVE: all contending leases must expire before resolution"
        )

    decision_sha, plan_sha, repository, run_id = next(iter(bindings))
    epoch = next(iter(epochs)) + 1
    return build_execution_lease(
        owner_id=owner_id,
        epoch=epoch,
        decision_record_sha256=decision_sha,
        effect_plan_sha256=plan_sha,
        repository=repository,
        run_id=run_id,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
        previous_lease_set_sha256=_lease_set_digest(contending_leases),
    )


def write_execution_lease(path: str | Path, lease: dict[str, Any]) -> str:
    verify_execution_lease(lease)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_bytes(lease)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return lease_digest(lease)


def read_execution_lease(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8")
        lease = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionLeaseError(f"could not read execution lease: {exc}") from exc
    verify_execution_lease(lease)
    return lease


def load_registry(directory: str | Path) -> list[dict[str, Any]]:
    root = Path(directory)
    if not root.exists():
        raise ExecutionLeaseError("execution lease registry directory does not exist")

    leases: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.execution-lease.json")):
        leases.append(read_execution_lease(path))
    if not leases:
        raise ExecutionLeaseError("execution lease registry is empty")
    return leases


def current_registry_lease(leases: list[dict[str, Any]]) -> dict[str, Any]:
    if not leases:
        raise ExecutionLeaseError("execution lease registry is empty")
    for lease in leases:
        verify_execution_lease(lease)

    max_epoch = max(int(item["epoch"]) for item in leases)
    current = [item for item in leases if int(item["epoch"]) == max_epoch]
    digests = {lease_digest(item) for item in current}
    if len(digests) != 1:
        raise ExecutionLeaseError(
            f"LEASE_EPOCH_CONFLICT: multiple distinct leases exist at epoch {max_epoch}"
        )
    return current[0]


def verify_effect_ownership(
    *,
    candidate_lease: dict[str, Any],
    registry_leases: list[dict[str, Any]],
    expected_owner_id: str,
    decision_record_sha256: str,
    effect_plan_sha256: str,
    repository: str,
    run_id: int,
    now: str,
) -> None:
    verify_execution_lease(candidate_lease)
    current = current_registry_lease(registry_leases)

    if lease_digest(candidate_lease) != lease_digest(current):
        raise ExecutionLeaseError(
            f"LEASE_SUPERSEDED: candidate epoch {candidate_lease['epoch']} is not current epoch {current['epoch']}"
        )
    if str(candidate_lease["owner_id"]) != str(expected_owner_id):
        raise ExecutionLeaseError("LEASE_OWNER_MISMATCH")
    if str(candidate_lease["decision_record_sha256"]) != str(decision_record_sha256).lower():
        raise ExecutionLeaseError("LEASE_DECISION_BINDING_MISMATCH")
    if str(candidate_lease["effect_plan_sha256"]) != str(effect_plan_sha256).lower():
        raise ExecutionLeaseError("LEASE_EFFECT_PLAN_BINDING_MISMATCH")
    if str(candidate_lease["repository"]) != str(repository):
        raise ExecutionLeaseError("LEASE_REPOSITORY_MISMATCH")
    if int(candidate_lease["run_id"]) != int(run_id):
        raise ExecutionLeaseError("LEASE_RUN_ID_MISMATCH")

    current_time = _parse_timestamp(now, field="evaluation_time")
    issued = _parse_timestamp(candidate_lease["issued_at"], field="issued_at")
    expires = _parse_timestamp(candidate_lease["expires_at"], field="expires_at")
    if current_time < issued:
        raise ExecutionLeaseError("LEASE_NOT_YET_VALID")
    if current_time >= expires:
        raise ExecutionLeaseError("LEASE_EXPIRED")
