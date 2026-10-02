"""Git-ref backed single-winner execution lease acquisition.

Each contender creates a sibling commit from the same observed coordination ref.
A non-force ref update can fast-forward to only one sibling. Later siblings are
non-fast-forward updates and therefore lose. The winning commit SHA is the
fencing token consumed at the effect boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ci_retry_gate import GitHubAPI, redact


class LinearizableLeaseError(ValueError):
    """Raised when the coordination record cannot be trusted."""


@dataclass(frozen=True, slots=True)
class ClaimResult:
    owner_id: str
    acquired: bool
    coordination_ref: str
    base_sha: str
    candidate_sha: str
    observed_sha: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "acquired": self.acquired,
            "coordination_ref": self.coordination_ref,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "observed_sha": self.observed_sha,
            "reason": self.reason,
        }


def _ref_path(coordination_ref: str) -> str:
    value = str(coordination_ref).strip()
    if not value.startswith("refs/heads/"):
        raise LinearizableLeaseError(
            "coordination_ref must be under refs/heads/"
        )
    return value[len("refs/") :]


def read_coordination_sha(
    api: GitHubAPI,
    repo: str,
    coordination_ref: str,
) -> str:
    ref_path = _ref_path(coordination_ref)
    payload = api.request("GET", f"/repos/{repo}/git/ref/{ref_path}")
    if not isinstance(payload, dict):
        raise LinearizableLeaseError("coordination ref response is not an object")
    obj = payload.get("object")
    if not isinstance(obj, dict):
        raise LinearizableLeaseError("coordination ref object is missing")
    sha = str(obj.get("sha") or "").strip()
    if len(sha) != 40:
        raise LinearizableLeaseError("coordination ref SHA is invalid")
    return sha


def create_coordination_ref(
    api: GitHubAPI,
    repo: str,
    coordination_ref: str,
    base_sha: str,
) -> str:
    _ref_path(coordination_ref)
    payload = api.request(
        "POST",
        f"/repos/{repo}/git/refs",
        {
            "ref": coordination_ref,
            "sha": base_sha,
        },
    )
    if not isinstance(payload, dict):
        raise LinearizableLeaseError("coordination ref creation returned no object")
    observed = read_coordination_sha(api, repo, coordination_ref)
    if observed != base_sha:
        raise LinearizableLeaseError(
            f"coordination ref base mismatch: expected {base_sha}, observed {observed}"
        )
    return observed


def delete_coordination_ref(
    api: GitHubAPI,
    repo: str,
    coordination_ref: str,
) -> None:
    ref_path = _ref_path(coordination_ref)
    api.request("DELETE", f"/repos/{repo}/git/refs/{ref_path}")


def _commit_tree_sha(api: GitHubAPI, repo: str, commit_sha: str) -> str:
    payload = api.request("GET", f"/repos/{repo}/git/commits/{commit_sha}")
    if not isinstance(payload, dict):
        raise LinearizableLeaseError("base commit response is not an object")
    tree = payload.get("tree")
    if not isinstance(tree, dict):
        raise LinearizableLeaseError("base commit tree is missing")
    tree_sha = str(tree.get("sha") or "").strip()
    if len(tree_sha) != 40:
        raise LinearizableLeaseError("base commit tree SHA is invalid")
    return tree_sha


def build_candidate_commit(
    api: GitHubAPI,
    repo: str,
    *,
    base_sha: str,
    owner_id: str,
    epoch: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> str:
    owner = str(owner_id).strip()
    if not owner:
        raise LinearizableLeaseError("owner_id is required")
    if int(epoch) < 1:
        raise LinearizableLeaseError("epoch must be positive")

    tree_sha = _commit_tree_sha(api, repo, base_sha)
    metadata = {
        "kind": "ci-retry-gate-linearizable-lease",
        "owner_id": owner,
        "epoch": int(epoch),
        "decision_record_sha256": str(decision_record_sha256),
        "effect_plan_sha256": str(effect_plan_sha256),
        "base_sha": str(base_sha),
    }
    message = (
        "ci-retry-gate linearizable lease claim\n\n"
        + json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    )
    payload = api.request(
        "POST",
        f"/repos/{repo}/git/commits",
        {
            "message": message,
            "tree": tree_sha,
            "parents": [base_sha],
        },
    )
    if not isinstance(payload, dict):
        raise LinearizableLeaseError("candidate commit response is not an object")
    candidate_sha = str(payload.get("sha") or "").strip()
    if len(candidate_sha) != 40:
        raise LinearizableLeaseError("candidate commit SHA is invalid")
    return candidate_sha


def publish_candidate(
    api: GitHubAPI,
    repo: str,
    *,
    coordination_ref: str,
    expected_base_sha: str,
    owner_id: str,
    candidate_sha: str,
) -> ClaimResult:
    observed_before = read_coordination_sha(api, repo, coordination_ref)
    if observed_before != expected_base_sha:
        return ClaimResult(
            owner_id=owner_id,
            acquired=False,
            coordination_ref=coordination_ref,
            base_sha=expected_base_sha,
            candidate_sha=candidate_sha,
            observed_sha=observed_before,
            reason=(
                "COORDINATION_BASE_CHANGED: "
                f"expected {expected_base_sha}, observed {observed_before}"
            ),
        )

    ref_path = _ref_path(coordination_ref)
    try:
        api.request(
            "PATCH",
            f"/repos/{repo}/git/refs/{ref_path}",
            {
                "sha": candidate_sha,
                "force": False,
            },
        )
    except RuntimeError as exc:
        observed_after = read_coordination_sha(api, repo, coordination_ref)
        return ClaimResult(
            owner_id=owner_id,
            acquired=False,
            coordination_ref=coordination_ref,
            base_sha=expected_base_sha,
            candidate_sha=candidate_sha,
            observed_sha=observed_after,
            reason=f"CAS_LOST: {redact(str(exc))}",
        )

    observed_after = read_coordination_sha(api, repo, coordination_ref)
    if observed_after != candidate_sha:
        raise LinearizableLeaseError(
            "coordination ref update returned without owning the candidate token"
        )

    return ClaimResult(
        owner_id=owner_id,
        acquired=True,
        coordination_ref=coordination_ref,
        base_sha=expected_base_sha,
        candidate_sha=candidate_sha,
        observed_sha=observed_after,
        reason="CAS_ACQUIRED",
    )


def try_claim(
    api: GitHubAPI,
    repo: str,
    *,
    coordination_ref: str,
    expected_base_sha: str,
    owner_id: str,
    epoch: int,
    decision_record_sha256: str,
    effect_plan_sha256: str,
) -> ClaimResult:
    observed_before = read_coordination_sha(api, repo, coordination_ref)
    if observed_before != expected_base_sha:
        return ClaimResult(
            owner_id=owner_id,
            acquired=False,
            coordination_ref=coordination_ref,
            base_sha=expected_base_sha,
            candidate_sha="",
            observed_sha=observed_before,
            reason=(
                "COORDINATION_BASE_CHANGED: "
                f"expected {expected_base_sha}, observed {observed_before}"
            ),
        )

    candidate_sha = build_candidate_commit(
        api,
        repo,
        base_sha=expected_base_sha,
        owner_id=owner_id,
        epoch=epoch,
        decision_record_sha256=decision_record_sha256,
        effect_plan_sha256=effect_plan_sha256,
    )
    return publish_candidate(
        api,
        repo,
        coordination_ref=coordination_ref,
        expected_base_sha=expected_base_sha,
        owner_id=owner_id,
        candidate_sha=candidate_sha,
    )


def verify_fencing_token(
    api: GitHubAPI,
    repo: str,
    *,
    coordination_ref: str,
    fencing_token_sha: str,
) -> None:
    token = str(fencing_token_sha).strip()
    if len(token) != 40:
        raise LinearizableLeaseError("fencing token SHA is invalid")
    observed = read_coordination_sha(api, repo, coordination_ref)
    if observed != token:
        raise LinearizableLeaseError(
            f"FENCING_TOKEN_STALE: expected {token}, observed {observed}"
        )
