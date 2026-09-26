"""Canonical EvidenceBundle persistence with integrity verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class EvidenceArtifactError(ValueError):
    """Raised when an EvidenceBundle artifact cannot be trusted or decoded."""


def canonical_evidence_bytes(bundle: dict[str, Any]) -> bytes:
    """Serialize an EvidenceBundle deterministically for storage and hashing."""
    return json.dumps(
        bundle,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def evidence_sha256(bundle: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_evidence_bytes(bundle)).hexdigest()


def write_evidence_artifact(path: str | Path, bundle: dict[str, Any]) -> str:
    """Write canonical evidence bytes atomically and return their SHA-256 digest."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_evidence_bytes(bundle)
    digest = hashlib.sha256(payload).hexdigest()

    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(payload + b"\n")
    temporary.replace(target)
    return digest


def read_evidence_artifact(
    path: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Read an EvidenceBundle and optionally verify its canonical SHA-256 digest."""
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise EvidenceArtifactError(f"could not read evidence artifact: {exc}") from exc

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceArtifactError(f"invalid evidence artifact JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise EvidenceArtifactError("evidence artifact root must be a JSON object")

    canonical = canonical_evidence_bytes(value)
    actual = hashlib.sha256(canonical).hexdigest()

    if expected_sha256 is not None:
        expected = expected_sha256.strip().lower()
        if not expected or actual != expected:
            raise EvidenceArtifactError(
                f"evidence artifact SHA-256 mismatch: expected {expected or '<empty>'}, "
                f"observed {actual}"
            )

    return value
