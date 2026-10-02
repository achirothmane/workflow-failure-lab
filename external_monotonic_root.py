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
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ci_retry_gate import GitHubAPI, redact


ROOT_SCHEMA = "ci-retry-gate.external-monotonic-root.v1"
ANCHOR_SCHEMA = "ci-retry-gate.external-monotonic-root-anchor.v1"
MAX_ATTESTATIONS = 100
MAX_BUNDLE_BYTES = 4 * 1024 * 1024
DEFAULT_PREDICATE_TYPE = (
    "https://github.com/achirothmane/workflow-failure-lab/"
    "attestations/external-monotonic-root/v1"
)


class ExternalMonotonicRootError(ValueError):
    """Raised when the independent high-water mark cannot be trusted."""


def _compact_error(value: object) -> str:
    return " ".join(redact(str(value)).split())


def _github_cli_env() -> dict[str, str]:
    env = os.environ.copy()
    if not env.get("GH_TOKEN"):
        token = env.get("GITHUB_TOKEN") or env.get("INPUT_GITHUB_TOKEN")
        if token:
            env["GH_TOKEN"] = token
    return env


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


def build_root_anchor(
    *,
    repository: str,
    run_id: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> dict[str, Any]:
    repo = str(repository).strip()
    if not repo:
        raise ExternalMonotonicRootError("repository is required")
    if int(run_id) < 1:
        raise ExternalMonotonicRootError("run_id must be positive")

    for field, value in (
        ("decision_record_sha256", decision_record_sha256),
        ("effect_plan_sha256", effect_plan_sha256),
    ):
        digest = str(value).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExternalMonotonicRootError(f"{field} must be SHA-256 hex")

    return seal_root_record(
        {
            "schema_version": ANCHOR_SCHEMA,
            "repository": repo,
            "run_id": int(run_id),
            "decision_record_sha256": str(decision_record_sha256).lower(),
            "effect_plan_sha256": str(effect_plan_sha256).lower(),
        }
    )


def verify_root_anchor(anchor: dict[str, Any]) -> None:
    if not isinstance(anchor, dict):
        raise ExternalMonotonicRootError("external root anchor must be an object")
    if anchor.get("schema_version") != ANCHOR_SCHEMA:
        raise ExternalMonotonicRootError("unsupported external root anchor schema")
    if not str(anchor.get("repository") or "").strip():
        raise ExternalMonotonicRootError("external root anchor repository is missing")
    try:
        run_id = int(anchor.get("run_id"))
    except (TypeError, ValueError) as exc:
        raise ExternalMonotonicRootError(
            "external root anchor run_id must be an integer"
        ) from exc
    if run_id < 1:
        raise ExternalMonotonicRootError("external root anchor run_id must be positive")

    for field in ("decision_record_sha256", "effect_plan_sha256"):
        digest = str(anchor.get(field) or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ExternalMonotonicRootError(f"external root anchor {field} is invalid")

    integrity = anchor.get("integrity")
    if not isinstance(integrity, dict):
        raise ExternalMonotonicRootError("external root anchor integrity is missing")
    if integrity.get("algorithm") != "sha256":
        raise ExternalMonotonicRootError(
            "external root anchor integrity algorithm is unsupported"
        )
    if integrity.get("digest") != root_record_digest(anchor):
        raise ExternalMonotonicRootError("external root anchor SHA-256 mismatch")


def write_root_anchor(path: str | Path, anchor: dict[str, Any]) -> str:
    verify_root_anchor(anchor)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_canonical_bytes(anchor) + b"\n")
    return root_record_digest(anchor)


def read_root_anchor(path: str | Path) -> dict[str, Any]:
    try:
        anchor = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExternalMonotonicRootError(
            f"could not read external root anchor: {exc}"
        ) from exc
    verify_root_anchor(anchor)
    return anchor


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


def write_predicate(
    path: str | Path,
    record: dict[str, Any],
    *,
    anchor: dict[str, Any],
) -> None:
    verify_root_record(record)
    verify_root_anchor(anchor)
    if (
        record["repository"] != anchor["repository"]
        or int(record["run_id"]) != int(anchor["run_id"])
        or record["decision_record_sha256"] != anchor["decision_record_sha256"]
        or record["effect_plan_sha256"] != anchor["effect_plan_sha256"]
    ):
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_ANCHOR_BINDING_MISMATCH")

    predicate = {
        "purpose": "execution-fencing-high-water-mark",
        "schema_version": ROOT_SCHEMA,
        "repository": record["repository"],
        "run_id": record["run_id"],
        "epoch": record["epoch"],
        "lifecycle_state": record["lifecycle_state"],
        "fencing_token_sha": record["fencing_token_sha"],
        "root_record_sha256": root_record_digest(record),
        "anchor_record_sha256": root_record_digest(anchor),
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
) -> list[dict[str, Any]]:
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
    env = _github_cli_env()

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
        detail = _compact_error(completed.stderr or completed.stdout or "")
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
    return result


def verify_sigstore_attestation_set(
    *,
    anchor_path: str | Path,
    repository: str,
    signer_workflow: str,
    predicate_type: str = DEFAULT_PREDICATE_TYPE,
) -> list[dict[str, Any]]:
    subject = Path(anchor_path)
    signer = str(signer_workflow).strip()
    predicate = str(predicate_type).strip()
    if not subject.is_file():
        raise ExternalMonotonicRootError("external root anchor file is missing")
    if not signer:
        raise ExternalMonotonicRootError("external root signer workflow is required")
    if not predicate:
        raise ExternalMonotonicRootError("external root predicate type is required")

    subject_digest = hashlib.sha256(subject.read_bytes()).hexdigest()
    encoded_predicate = urllib.parse.quote(predicate, safe="")
    endpoint = (
        f"/repos/{repository}/attestations/sha256:{subject_digest}"
        f"?per_page={MAX_ATTESTATIONS}&predicate_type={encoded_predicate}"
    )
    command = [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        endpoint,
    ]
    env = _github_cli_env()

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
            f"could not list external root attestations: {_compact_error(exc)}"
        ) from exc

    if completed.returncode != 0:
        detail = _compact_error(completed.stderr or completed.stdout or "")
        raise ExternalMonotonicRootError(
            f"GITHUB_ATTESTATION_DISCOVERY_FAILED: "
            f"{detail or 'repository attestation lookup failed'}"
        )

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ExternalMonotonicRootError(
            "GITHUB_ATTESTATION_DISCOVERY_FAILED: API returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ExternalMonotonicRootError(
            "GITHUB_ATTESTATION_DISCOVERY_FAILED: API returned non-object JSON"
        )

    attestations = payload.get("attestations")
    if not isinstance(attestations, list) or not attestations:
        raise ExternalMonotonicRootError(
            "NO_TRUSTED_EXTERNAL_ROOT_ATTESTATION"
        )
    if len(attestations) >= MAX_ATTESTATIONS:
        raise ExternalMonotonicRootError(
            "EXTERNAL_ROOT_ATTESTATION_SET_TRUNCATED"
        )

    verified: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="external-root-attestations-") as tmp:
        for index, entry in enumerate(attestations):
            if not isinstance(entry, dict):
                raise ExternalMonotonicRootError(
                    "GITHUB_ATTESTATION_DISCOVERY_FAILED: malformed attestation entry"
                )
            bundle_url = str(entry.get("bundle_url") or "").strip()
            parsed = urllib.parse.urlparse(bundle_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise ExternalMonotonicRootError(
                    "GITHUB_ATTESTATION_DISCOVERY_FAILED: invalid bundle URL"
                )

            request = urllib.request.Request(
                bundle_url,
                headers={"User-Agent": "ci-retry-gate-external-root"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    bundle_bytes = response.read(MAX_BUNDLE_BYTES + 1)
            except (OSError, urllib.error.URLError) as exc:
                raise ExternalMonotonicRootError(
                    "ATTESTATION_BUNDLE_DOWNLOAD_FAILED: "
                    f"{type(exc).__name__}"
                ) from exc
            if len(bundle_bytes) > MAX_BUNDLE_BYTES:
                raise ExternalMonotonicRootError(
                    "ATTESTATION_BUNDLE_TOO_LARGE"
                )

            bundle_path = Path(tmp) / f"bundle-{index}.json"
            bundle_path.write_bytes(bundle_bytes)
            verified.extend(
                verify_sigstore_attestation(
                    root_record_path=subject,
                    bundle_path=bundle_path,
                    repository=repository,
                    signer_workflow=signer,
                    predicate_type=predicate,
                )
            )

    if not verified:
        raise ExternalMonotonicRootError(
            "NO_TRUSTED_EXTERNAL_ROOT_ATTESTATION"
        )
    return verified

def verify_anchor_binding(
    anchor: dict[str, Any],
    *,
    repository: str,
    run_id: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> None:
    verify_root_anchor(anchor)
    if str(anchor["repository"]) != str(repository):
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_ANCHOR_REPOSITORY_MISMATCH")
    if int(anchor["run_id"]) != int(run_id):
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_ANCHOR_RUN_ID_MISMATCH")
    if str(anchor["decision_record_sha256"]) != str(decision_record_sha256).lower():
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_ANCHOR_DECISION_MISMATCH")
    if str(anchor["effect_plan_sha256"]) != str(effect_plan_sha256).lower():
        raise ExternalMonotonicRootError("EXTERNAL_ROOT_ANCHOR_EFFECT_PLAN_MISMATCH")


def verify_latest_root_attestation(
    record: dict[str, Any],
    anchor: dict[str, Any],
    verified_attestations: list[dict[str, Any]],
    *,
    predicate_type: str,
) -> int:
    verify_root_record(record)
    verify_root_anchor(anchor)
    anchor_digest = root_record_digest(anchor)
    candidates: list[dict[str, Any]] = []

    for item in verified_attestations:
        if not isinstance(item, dict):
            continue
        verification = item.get("verificationResult")
        if not isinstance(verification, dict):
            continue
        statement = verification.get("statement")
        if not isinstance(statement, dict):
            continue
        if str(statement.get("predicateType") or "") != str(predicate_type):
            continue
        predicate = statement.get("predicate")
        if not isinstance(predicate, dict):
            continue
        if predicate.get("purpose") != "execution-fencing-high-water-mark":
            continue
        if predicate.get("schema_version") != ROOT_SCHEMA:
            continue
        if str(predicate.get("repository") or "") != str(anchor["repository"]):
            continue
        try:
            predicate_run_id = int(predicate.get("run_id"))
            epoch = int(predicate.get("epoch"))
        except (TypeError, ValueError):
            continue
        if predicate_run_id != int(anchor["run_id"]) or epoch < 1:
            continue
        if str(predicate.get("anchor_record_sha256") or "").lower() != anchor_digest:
            continue

        root_digest = str(predicate.get("root_record_sha256") or "").strip().lower()
        if len(root_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in root_digest
        ):
            continue
        state = str(predicate.get("lifecycle_state") or "").strip().upper()
        if state not in {"EXECUTABLE", "CLOSED"}:
            continue
        token = str(predicate.get("fencing_token_sha") or "").strip().lower()
        if len(token) != 40 or any(ch not in "0123456789abcdef" for ch in token):
            continue
        candidates.append(
            {
                "epoch": epoch,
                "root_record_sha256": root_digest,
                "lifecycle_state": state,
                "fencing_token_sha": token,
            }
        )

    if not candidates:
        raise ExternalMonotonicRootError(
            "NO_TRUSTED_EXTERNAL_ROOT_ATTESTATION"
        )

    latest_epoch = max(int(candidate["epoch"]) for candidate in candidates)
    latest = [candidate for candidate in candidates if int(candidate["epoch"]) == latest_epoch]
    latest_digests = {
        str(candidate["root_record_sha256"]) for candidate in latest
    }
    if len(latest_digests) != 1:
        raise ExternalMonotonicRootError(
            f"EXTERNAL_ROOT_FORK_AT_MAX_EPOCH: epoch={latest_epoch}"
        )

    supplied_epoch = int(record["epoch"])
    if supplied_epoch < latest_epoch:
        raise ExternalMonotonicRootError(
            "STALE_EXTERNAL_ROOT_ATTESTATION: "
            f"supplied_epoch={supplied_epoch} latest_epoch={latest_epoch}"
        )
    if supplied_epoch > latest_epoch:
        raise ExternalMonotonicRootError(
            "UNATTESTED_EXTERNAL_ROOT_EPOCH: "
            f"supplied_epoch={supplied_epoch} latest_epoch={latest_epoch}"
        )

    supplied_digest = root_record_digest(record)
    expected_digest = next(iter(latest_digests))
    if supplied_digest != expected_digest:
        raise ExternalMonotonicRootError(
            "EXTERNAL_ROOT_ATTESTATION_MISMATCH"
        )

    authoritative = latest[0]
    if (
        str(authoritative["lifecycle_state"]) != str(record["lifecycle_state"])
        or str(authoritative["fencing_token_sha"]) != str(record["fencing_token_sha"])
    ):
        raise ExternalMonotonicRootError(
            "EXTERNAL_ROOT_ATTESTATION_MISMATCH"
        )
    return latest_epoch


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
    anchor_path: str | Path,
    attestation_bundle_path: str | Path,
    signer_workflow: str,
    predicate_type: str,
    presented_token_sha: str,
    run_id: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> dict[str, Any]:
    record = read_root_record(root_record_path)
    anchor = read_root_anchor(anchor_path)
    verify_root_binding(
        record,
        repository=repo,
        run_id=run_id,
        decision_record_sha256=decision_record_sha256,
        effect_plan_sha256=effect_plan_sha256,
    )
    verify_anchor_binding(
        anchor,
        repository=repo,
        run_id=run_id,
        decision_record_sha256=decision_record_sha256,
        effect_plan_sha256=effect_plan_sha256,
    )

    # First prove the specifically supplied bundle is authentic for the stable
    # decision anchor. This preserves offline proof of the concrete root.
    verify_sigstore_attestation(
        root_record_path=anchor_path,
        bundle_path=attestation_bundle_path,
        repository=repo,
        signer_workflow=signer_workflow,
        predicate_type=predicate_type,
    )

    # Then resolve every currently verifiable attestation for the same stable
    # anchor. A valid old bundle is not sufficient if a later epoch exists.
    verified_attestations = verify_sigstore_attestation_set(
        anchor_path=anchor_path,
        repository=repo,
        signer_workflow=signer_workflow,
        predicate_type=predicate_type,
    )
    verify_latest_root_attestation(
        record,
        anchor,
        verified_attestations,
        predicate_type=predicate_type,
    )

    verify_token_not_below_root(
        api,
        repo,
        root_token_sha=str(record["fencing_token_sha"]),
        presented_token_sha=presented_token_sha,
    )
    return record
