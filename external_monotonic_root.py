"""Independent monotonic execution root backed by Sigstore attestations.

The mutable Git refs remain the fast-path coordination layer. This module adds an
external high-water mark that is cryptographically attested outside that local
ref state. A presented fencing token must be equal to, or descend from, the
attested root token before it may reach the Effect boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ci_retry_gate import GitHubAPI, redact


ROOT_SCHEMA = "ci-retry-gate.external-monotonic-root.v1"
DEFAULT_PREDICATE_TYPE = (
    "https://github.com/achirothmane/workflow-failure-lab/"
    "attestations/external-monotonic-root/v1"
)


class ExternalMonotonicRootError(ValueError):
    """Raised when the independent high-water mark cannot be trusted."""


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def root_record_digest(record: dict[str, Any]) -> str:
    unsigned = dict(record)
    unsigned.pop("integrity", None)
    return _sha256(unsigned)


def seal_root_record(record: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(record)
    sealed.pop("integrity", None)
    sealed["integrity"] = {
        "algorithm": "sha256",
        "digest": _sha256(sealed),
    }
    return sealed


def build_root_record(
    *,
    repository: str,
    run_id: int,
    epoch: int,
    fencing_token_sha: str,
    decision_record_sha256: str,
    effect_plan_sha256: str,
    lifecycle_state: str,
) -> dict[str, Any]:
    state = str(lifecycle_state).strip().upper()
    if state not in {"EXECUTABLE", "CLOSED"}:
        raise ExternalMonotonicRootError(
            "lifecycle_state must be EXECUTABLE or CLOSED"
        )
    token = str(fencing_token_sha).strip().lower()
    if len(token) != 40 or any(ch not in "0123456789abcdef" for ch in token):
        raise ExternalMonotonicRootError("fencing_token_sha must be a git SHA-1")

    for field, value in (
        ("decision_record_sha256", decision_record_sha256),
        ("effect_plan_sha256", effect_plan_sha256),
    ):
        digest = str(value).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExternalMonotonicRootError(f"{field} must be SHA-256 hex")

    if int(run_id) < 1 or int(epoch) < 1:
        raise ExternalMonotonicRootError("run_id and epoch must be positive")

    record = {
        "schema_version": ROOT_SCHEMA,
        "repository": str(repository),
        "run_id": int(run_id),
        "epoch": int(epoch),
        "fencing_token_sha": token,
        "decision_record_sha256": str(decision_record_sha256).lower(),
        "effect_plan_sha256": str(effect_plan_sha256).lower(),
        "lifecycle_state": state,
    }
    return seal_root_record(record)


def verify_root_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ExternalMonotonicRootError("external root must be an object")
    if record.get("schema_version") != ROOT_SCHEMA:
        raise ExternalMonotonicRootError("unsupported external root schema")

    token = str(record.get("fencing_token_sha") or "").strip().lower()
    if len(token) != 40 or any(ch not in "0123456789abcdef" for ch in token):
        raise ExternalMonotonicRootError("external root token SHA is invalid")

    try:
        run_id = int(record.get("run_id"))
        epoch = int(record.get("epoch"))
    except (TypeError, ValueError) as exc:
        raise ExternalMonotonicRootError(
            "external root run_id/epoch must be integers"
        ) from exc
    if run_id < 1 or epoch < 1:
        raise ExternalMonotonicRootError(
            "external root run_id/epoch must be positive"
        )

    state = str(record.get("lifecycle_state") or "").strip().upper()
    if state not in {"EXECUTABLE", "CLOSED"}:
        raise ExternalMonotonicRootError("external root lifecycle state is invalid")

    for field in ("decision_record_sha256", "effect_plan_sha256"):
        digest = str(record.get(field) or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExternalMonotonicRootError(f"external root {field} is invalid")

    integrity = record.get("integrity")
    if not isinstance(integrity, dict):
        raise ExternalMonotonicRootError("external root integrity metadata is missing")
    if integrity.get("algorithm") != "sha256":
        raise ExternalMonotonicRootError(
            "external root integrity algorithm is unsupported"
        )
    if integrity.get("digest") != root_record_digest(record):
        raise ExternalMonotonicRootError("external root SHA-256 mismatch")


def write_root_record(path: str | Path, record: dict[str, Any]) -> str:
    verify_root_record(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical_bytes(record) + b"\n")
    return root_record_digest(record)


def read_root_record(path: str | Path) -> dict[str, Any]:
    try:
        record = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalMonotonicRootError(
            f"could not read external root record: {exc}"
        ) from exc
    verify_root_record(record)
    return record


def write_predicate(path: str | Path, record: dict[str, Any]) -> None:
    verify_root_record(record)
    predicate = {
        "purpose": "execution-fencing-high-water-mark",
        "schema_version": ROOT_SCHEMA,
        "repository": record["repository"],
        "run_id": record["run_id"],
        "epoch": record["epoch"],
        "lifecycle_state": record["lifecycle_state"],
        "root_record_sha256": root_record_digest(record),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical_bytes(predicate) + b"\n")


def verify_sigstore_attestation(
    *,
    root_record_path: str | Path,
    bundle_path: str | Path,
    repository: str,
    signer_workflow: str,
    predicate_type: str = DEFAULT_PREDICATE_TYPE,
) -> None:
    record_path = str(Path(root_record_path))
    bundle = str(Path(bundle_path))
    signer = str(signer_workflow).strip()
    predicate = str(predicate_type).strip()
    if not signer:
        raise ExternalMonotonicRootError("external root signer workflow is required")
    if not predicate:
        raise ExternalMonotonicRootError("external root predicate type is required")
    if not Path(record_path).is_file():
        raise ExternalMonotonicRootError("external root record file is missing")
    if not Path(bundle).is_file():
        raise ExternalMonotonicRootError("external root attestation bundle is missing")

    command = [
        "gh",
        "attestation",
        "verify",
        record_path,
        "--repo",
        repository,
        "--bundle",
        bundle,
        "--predicate-type",
        predicate,
        "--signer-workflow",
        signer,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]
    env = os.environ.copy()
    if env.get("GITHUB_TOKEN") and not env.get("GH_TOKEN"):
        env["GH_TOKEN"] = env["GITHUB_TOKEN"]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExternalMonotonicRootError(
            f"could not invoke Sigstore attestation verifier: {exc}"
        ) from exc

    if completed.returncode != 0:
        detail = redact((completed.stderr or completed.stdout or "").strip())
        raise ExternalMonotonicRootError(
            f"SIGSTORE_ATTESTATION_INVALID: {detail or 'verification failed'}"
        )

    try:
        result = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise ExternalMonotonicRootError(
            "SIGSTORE_ATTESTATION_INVALID: verifier returned invalid JSON"
        ) from exc
    if not isinstance(result, list) or not result:
        raise ExternalMonotonicRootError(
            "SIGSTORE_ATTESTATION_INVALID: no verified attestation"
        )


def verify_root_binding(
    record: dict[str, Any],
    *,
    repository: str,
    run_id: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> None:
    verify_root_record(record)
    if str(record["repository"]) != str(repository):
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_REPOSITORY_MISMATCH")
    if int(record["run_id"]) != int(run_id):
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_RUN_ID_MISMATCH")
    if str(record["decision_record_sha256"]) != str(
        decision_record_sha256
    ).lower():
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_DECISION_BINDING_MISMATCH")
    if str(record["effect_plan_sha256"]) != str(effect_plan_sha256).lower():
        raise ExternalMonotonicRootError(
            "EXTERNAL_ROOT_EFFECT_PLAN_BINDING_MISMATCH"
        )


def verify_token_not_below_root(
    api: GitHubAPI,
    repo: str,
    *,
    root_token_sha: str,
    presented_token_sha: str,
) -> None:
    root = str(root_token_sha).strip().lower()
    presented = str(presented_token_sha).strip().lower()
    if root == presented:
        return
    if len(root) != 40 or len(presented) != 40:
        raise ExternalMonotonicRootError("external root token comparison SHA is invalid")

    payload = api.request(
        "GET",
        f"/repos/{repo}/compare/{root}...{presented}",
    )
    if not isinstance(payload, dict):
        raise ExternalMonotonicRootError(
            "external root compare response is not an object"
        )
    status = str(payload.get("status") or "").strip().lower()
    ahead_by = int(payload.get("ahead_by") or 0)
    behind_by = int(payload.get("behind_by") or 0)

    if status == "ahead" and ahead_by > 0 and behind_by == 0:
        return

    raise ExternalMonotonicRootError(
        "TOKEN_BELOW_EXTERNAL_MONOTONIC_ROOT: "
        f"root={root} presented={presented} status={status or 'unknown'} "
        f"ahead_by={ahead_by} behind_by={behind_by}"
    )


def verify_external_monotonic_root(
    api: GitHubAPI,
    repo: str,
    *,
    root_record_path: str | Path,
    attestation_bundle_path: str | Path,
    signer_workflow: str,
    predicate_type: str,
    presented_token_sha: str,
    run_id: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> dict[str, Any]:
    record = read_root_record(root_record_path)
    verify_sigstore_attestation(
        root_record_path=root_record_path,
        bundle_path=attestation_bundle_path,
        repository=repo,
        signer_workflow=signer_workflow,
        predicate_type=predicate_type,
    )
    verify_root_binding(
        record,
        repository=repo,
        run_id=run_id,
        decision_record_sha256=decision_record_sha256,
        effect_plan_sha256=effect_plan_sha256,
    )
    verify_token_not_below_root(
        api,
        repo,
        root_token_sha=str(record["fencing_token_sha"]),
        presented_token_sha=presented_token_sha,
    )
    return record
