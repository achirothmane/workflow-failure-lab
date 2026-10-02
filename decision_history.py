"""Discover and verify prior CI Retry Gate audit artifacts.

This module is deliberately read-only. Historical audit records can enrich
observation/reconciliation but can never authorize the current retry attempt.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any

from decision_record import DecisionRecordError, verify_decision_record
from eba_integration_contract import RECEIPT_KIND, canonical_json_bytes


_ARTIFACT_SUFFIX_RE = re.compile(r"^(?P<digest>[0-9a-f]{12}|[0-9a-f]{64})$")


class DecisionHistoryError(ValueError):
    """Raised when prior audit history is ambiguous, malformed, or untrusted."""


@dataclass(frozen=True, slots=True)
class DecisionArtifactRef:
    artifact_id: int
    name: str
    digest_anchor: str
    workflow_run_id: int | None = None


@dataclass(frozen=True, slots=True)
class PriorAuditTrail:
    artifact: DecisionArtifactRef
    decision_record: dict[str, Any]
    execution_receipt: dict[str, Any] | None


def decision_artifact_prefix(*, run_id: int, run_attempt: int) -> str:
    return f"ci-retry-gate-der-{int(run_id)}-attempt-{int(run_attempt)}-"


def _artifact_ref(
    artifact: dict[str, Any],
    *,
    prefix: str,
) -> DecisionArtifactRef | None:
    if bool(artifact.get("expired")):
        return None

    name = str(artifact.get("name") or "")
    if not name.startswith(prefix):
        return None

    suffix = name[len(prefix) :]
    match = _ARTIFACT_SUFFIX_RE.fullmatch(suffix)
    if match is None:
        return None

    try:
        artifact_id = int(artifact.get("id"))
    except (TypeError, ValueError):
        return None

    workflow_run = artifact.get("workflow_run")
    workflow_run_id: int | None = None
    if isinstance(workflow_run, dict):
        try:
            raw_id = workflow_run.get("id")
            if raw_id is not None:
                workflow_run_id = int(raw_id)
        except (TypeError, ValueError):
            workflow_run_id = None

    return DecisionArtifactRef(
        artifact_id=artifact_id,
        name=name,
        digest_anchor=match.group("digest"),
        workflow_run_id=workflow_run_id,
    )


def find_previous_decision_artifact(
    api: Any,
    repo: str,
    *,
    run_id: int,
    current_attempt: int,
    max_pages: int = 5,
) -> DecisionArtifactRef | None:
    """Find one unique non-expired DER artifact for attempt N-1.

    Multiple matching artifacts are intentionally ambiguous. We never choose
    "latest" because completion order is not an authority signal.
    """
    if current_attempt <= 1:
        return None

    prior_attempt = current_attempt - 1
    prefix = decision_artifact_prefix(run_id=run_id, run_attempt=prior_attempt)
    matches: list[DecisionArtifactRef] = []

    for page in range(1, max_pages + 1):
        payload = api.request(
            "GET",
            f"/repos/{repo}/actions/artifacts?per_page=100&page={page}",
        )
        if not isinstance(payload, dict):
            raise DecisionHistoryError("GitHub artifacts API returned a non-object payload")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise DecisionHistoryError("GitHub artifacts API omitted artifacts array")

        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            ref = _artifact_ref(artifact, prefix=prefix)
            if ref is not None:
                matches.append(ref)

        if len(artifacts) < 100:
            break

    if not matches:
        return None
    if len(matches) != 1:
        names = ", ".join(sorted(item.name for item in matches[:5]))
        raise DecisionHistoryError(
            f"ambiguous prior decision history: found {len(matches)} artifacts "
            f"for run {run_id} attempt {prior_attempt}: {names}"
        )
    return matches[0]


def find_matching_receipt_artifact(
    api: Any,
    repo: str,
    decision_artifact: DecisionArtifactRef,
    *,
    max_pages: int = 5,
) -> int | None:
    """Find the unique receipt artifact paired with one DER artifact."""
    expected_name = decision_artifact.name + "-receipt"
    matches: list[int] = []

    for page in range(1, max_pages + 1):
        payload = api.request(
            "GET",
            f"/repos/{repo}/actions/artifacts?per_page=100&page={page}",
        )
        if not isinstance(payload, dict):
            raise DecisionHistoryError("GitHub artifacts API returned a non-object payload")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise DecisionHistoryError("GitHub artifacts API omitted artifacts array")

        for item in artifacts:
            if not isinstance(item, dict):
                continue
            if bool(item.get("expired")):
                continue
            if str(item.get("name") or "") != expected_name:
                continue
            try:
                matches.append(int(item.get("id")))
            except (TypeError, ValueError):
                continue

        if len(artifacts) < 100:
            break

    if not matches:
        return None
    if len(matches) != 1:
        raise DecisionHistoryError(
            f"ambiguous execution receipt history: found {len(matches)} artifacts "
            f"named {expected_name!r}"
        )
    return matches[0]


def _verify_receipt_integrity(receipt: object) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise DecisionHistoryError("execution receipt root must be an object")
    if receipt.get("kind") != RECEIPT_KIND:
        raise DecisionHistoryError(
            f"unexpected execution receipt kind={receipt.get('kind')!r}"
        )

    integrity = receipt.get("integrity")
    if not isinstance(integrity, dict):
        raise DecisionHistoryError("execution receipt integrity is missing")
    if integrity.get("algorithm") != "sha256":
        raise DecisionHistoryError("execution receipt integrity algorithm is unsupported")

    expected = str(integrity.get("digest") or "").strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise DecisionHistoryError("execution receipt integrity digest is invalid")

    semantic = dict(receipt)
    semantic.pop("integrity", None)
    actual = hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()
    if actual != expected:
        raise DecisionHistoryError(
            f"execution receipt SHA-256 mismatch: embedded {expected}, observed {actual}"
        )

    return receipt


def download_prior_audit_trail(
    api: Any,
    repo: str,
    artifact: DecisionArtifactRef,
) -> PriorAuditTrail:
    """Download one artifact ZIP and verify its DER and optional EBA receipt."""
    raw_zip = api.request_bytes(
        "GET",
        f"/repos/{repo}/actions/artifacts/{artifact.artifact_id}/zip",
    )

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw_zip))
    except zipfile.BadZipFile as exc:
        raise DecisionHistoryError("prior decision artifact is not a valid ZIP") from exc

    names = archive.namelist()
    decision_names = [
        name for name in names if name.endswith(".decision-record.json") and not name.endswith("/")
    ]
    if len(decision_names) != 1:
        raise DecisionHistoryError(
            f"expected exactly one Decision Evidence Record, found {len(decision_names)}"
        )

    try:
        decision = json.loads(archive.read(decision_names[0]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
        raise DecisionHistoryError("prior Decision Evidence Record is invalid JSON") from exc

    try:
        trusted = verify_decision_record(decision)
    except DecisionRecordError as exc:
        raise DecisionHistoryError(f"prior Decision Evidence Record failed verification: {exc}") from exc

    embedded_digest = str(trusted["record_sha256"])
    if not embedded_digest.startswith(artifact.digest_anchor):
        raise DecisionHistoryError(
            "prior Decision Evidence Record digest does not match artifact-name anchor"
        )

    receipt_names = [
        name for name in names if name.endswith(".eba-receipt.json") and not name.endswith("/")
    ]
    receipt: dict[str, Any] | None = None
    if len(receipt_names) > 1:
        raise DecisionHistoryError(
            f"expected at most one execution receipt, found {len(receipt_names)}"
        )
    if receipt_names:
        try:
            raw_receipt = json.loads(archive.read(receipt_names[0]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise DecisionHistoryError("prior execution receipt is invalid JSON") from exc
        receipt = _verify_receipt_integrity(raw_receipt)
    else:
        receipt_artifact_id = find_matching_receipt_artifact(
            api,
            repo,
            artifact,
        )
        if receipt_artifact_id is not None:
            raw_receipt_zip = api.request_bytes(
                "GET",
                f"/repos/{repo}/actions/artifacts/{receipt_artifact_id}/zip",
            )
            try:
                receipt_archive = zipfile.ZipFile(io.BytesIO(raw_receipt_zip))
            except zipfile.BadZipFile as exc:
                raise DecisionHistoryError(
                    "prior execution receipt artifact is not a valid ZIP"
                ) from exc
            external_receipt_names = [
                name
                for name in receipt_archive.namelist()
                if name.endswith(".eba-receipt.json") and not name.endswith("/")
            ]
            if len(external_receipt_names) != 1:
                raise DecisionHistoryError(
                    "expected exactly one execution receipt in receipt artifact, "
                    f"found {len(external_receipt_names)}"
                )
            try:
                raw_receipt = json.loads(
                    receipt_archive.read(external_receipt_names[0]).decode("utf-8")
                )
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
                raise DecisionHistoryError(
                    "prior external execution receipt is invalid JSON"
                ) from exc
            receipt = _verify_receipt_integrity(raw_receipt)

    return PriorAuditTrail(
        artifact=artifact,
        decision_record=trusted,
        execution_receipt=receipt,
    )
