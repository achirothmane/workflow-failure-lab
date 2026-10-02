from __future__ import annotations

import hashlib

import pytest

from linearizable_lease import (
    LinearizableLeaseError,
    build_candidate_commit,
    build_tombstone_commit,
    create_coordination_ref,
    publish_candidate,
    read_coordination_sha,
    verify_fencing_token,
)


class FakeGitHubAPI:
    def __init__(self):
        self.refs: dict[str, str] = {}
        self.commits: dict[str, dict] = {
            "a" * 40: {
                "tree": {"sha": "1" * 40},
                "parents": [],
                "message": "base",
            }
        }
        self.counter = 0

    def request(self, method: str, path: str, payload: dict | None = None, accept: str = "application/vnd.github+json"):
        del accept
        if method == "POST" and path.endswith("/git/refs"):
            ref = payload["ref"]
            if ref in self.refs:
                raise RuntimeError("HTTP 422 ref already exists")
            self.refs[ref] = payload["sha"]
            return {"ref": ref, "object": {"sha": payload["sha"]}}

        if method == "GET" and "/git/ref/" in path:
            suffix = path.split("/git/ref/", 1)[1]
            ref = "refs/" + suffix
            if ref not in self.refs:
                raise RuntimeError("HTTP 404 ref missing")
            return {"ref": ref, "object": {"sha": self.refs[ref]}}

        if method == "GET" and "/git/commits/" in path:
            sha = path.rsplit("/", 1)[1]
            return self.commits[sha]

        if method == "POST" and path.endswith("/git/commits"):
            self.counter += 1
            raw = f"{self.counter}:{payload['message']}:{payload['parents'][0]}".encode()
            sha = hashlib.sha1(raw).hexdigest()
            self.commits[sha] = {
                "tree": {"sha": payload["tree"]},
                "parents": [{"sha": payload["parents"][0]}],
                "message": payload["message"],
            }
            return {"sha": sha}

        if method == "PATCH" and "/git/refs/" in path:
            suffix = path.split("/git/refs/", 1)[1]
            ref = "refs/" + suffix
            current = self.refs[ref]
            candidate = payload["sha"]
            parent = self.commits[candidate]["parents"][0]["sha"]
            if payload.get("force") is not False:
                raise AssertionError("test requires non-force update")
            if parent != current:
                raise RuntimeError("HTTP 422 non-fast-forward")
            self.refs[ref] = candidate
            return {"ref": ref, "object": {"sha": candidate}}

        if method == "DELETE" and "/git/refs/" in path:
            suffix = path.split("/git/refs/", 1)[1]
            self.refs.pop("refs/" + suffix, None)
            return ""

        raise AssertionError((method, path, payload))


def test_sibling_candidates_from_same_base_have_exactly_one_winner():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    ref = "refs/heads/ci-retry-gate-linearizable/123"
    base = "a" * 40

    create_coordination_ref(api, repo, ref, base)

    b = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="claimant-b",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    c = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="claimant-c",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    assert b != c

    first = publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="claimant-b",
        candidate_sha=b,
    )
    second = publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="claimant-c",
        candidate_sha=c,
    )

    assert first.acquired is True
    assert second.acquired is False
    assert read_coordination_sha(api, repo, ref) == b
    assert second.observed_sha == b


def test_fencing_token_tracks_current_coordination_ref():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    ref = "refs/heads/ci-retry-gate-linearizable/123"
    base = "a" * 40

    create_coordination_ref(api, repo, ref, base)
    candidate = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="winner",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    result = publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="winner",
        candidate_sha=candidate,
    )
    assert result.acquired

    verify_fencing_token(
        api,
        repo,
        coordination_ref=ref,
        fencing_token_sha=candidate,
        expected_decision_record_sha256="b" * 64,
        expected_effect_plan_sha256="c" * 64,
    )

    with pytest.raises(LinearizableLeaseError, match="FENCING_TOKEN_STALE"):
        verify_fencing_token(
            api,
            repo,
            coordination_ref=ref,
            fencing_token_sha=base,
        )


def test_changed_base_cannot_be_reused_as_cas_precondition():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    ref = "refs/heads/ci-retry-gate-linearizable/123"
    base = "a" * 40

    create_coordination_ref(api, repo, ref, base)
    winner = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="winner",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="winner",
        candidate_sha=winner,
    )

    late = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="late",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    result = publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="late",
        candidate_sha=late,
    )

    assert result.acquired is False
    assert result.reason.startswith("CAS_LOST:")
    assert result.observed_sha == winner


def test_coordination_ref_must_live_under_heads():
    api = FakeGitHubAPI()

    with pytest.raises(LinearizableLeaseError, match="refs/heads"):
        create_coordination_ref(
            api,
            "owner/repo",
            "refs/tags/not-allowed",
            "a" * 40,
        )



def test_delete_recreate_of_coordination_ref_cannot_resurrect_old_token_with_witness():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    coord = "refs/heads/ci-retry-gate-linearizable/123"
    witness = "refs/heads/ci-retry-gate-linearizable-witness/123"
    base = "a" * 40

    create_coordination_ref(api, repo, coord, base)
    create_coordination_ref(api, repo, witness, base)

    token1 = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="worker-a",
        epoch=1,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    assert publish_candidate(
        api,
        repo,
        coordination_ref=coord,
        expected_base_sha=base,
        owner_id="worker-a",
        candidate_sha=token1,
    ).acquired
    assert publish_candidate(
        api,
        repo,
        coordination_ref=witness,
        expected_base_sha=base,
        owner_id="worker-a-witness",
        candidate_sha=token1,
    ).acquired

    token2 = build_candidate_commit(
        api,
        repo,
        base_sha=token1,
        owner_id="worker-b",
        epoch=2,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    assert publish_candidate(
        api,
        repo,
        coordination_ref=coord,
        expected_base_sha=token1,
        owner_id="worker-b",
        candidate_sha=token2,
    ).acquired
    assert publish_candidate(
        api,
        repo,
        coordination_ref=witness,
        expected_base_sha=token1,
        owner_id="worker-b-witness",
        candidate_sha=token2,
    ).acquired

    # Simulate the stronger ABA attack: delete the mutable coordination record
    # and recreate it at the previously valid token1. The durable witness is not
    # rewound.
    api.refs.pop(coord)
    create_coordination_ref(api, repo, coord, token1)

    with pytest.raises(LinearizableLeaseError, match="ABA_WITNESS_MISMATCH"):
        verify_fencing_token(
            api,
            repo,
            coordination_ref=coord,
            witness_ref=witness,
            fencing_token_sha=token1,
            expected_decision_record_sha256="b" * 64,
            expected_effect_plan_sha256="c" * 64,
        )


def test_fencing_token_is_bound_to_exact_decision_and_effect_plan():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    ref = "refs/heads/ci-retry-gate-linearizable/123"
    base = "a" * 40

    create_coordination_ref(api, repo, ref, base)
    token = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="winner",
        epoch=1,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    assert publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="winner",
        candidate_sha=token,
    ).acquired

    with pytest.raises(
        LinearizableLeaseError,
        match="FENCING_TOKEN_DECISION_BINDING_MISMATCH",
    ):
        verify_fencing_token(
            api,
            repo,
            coordination_ref=ref,
            fencing_token_sha=token,
            expected_decision_record_sha256="d" * 64,
            expected_effect_plan_sha256="c" * 64,
        )


def test_closed_tombstone_can_never_be_used_as_effect_authority():
    api = FakeGitHubAPI()
    repo = "owner/repo"
    ref = "refs/heads/ci-retry-gate-linearizable/123"
    base = "a" * 40

    create_coordination_ref(api, repo, ref, base)
    token = build_candidate_commit(
        api,
        repo,
        base_sha=base,
        owner_id="winner",
        epoch=1,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )
    assert publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=base,
        owner_id="winner",
        candidate_sha=token,
    ).acquired

    tombstone = build_tombstone_commit(
        api,
        repo,
        base_sha=token,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
        reason="reconciliation-closed",
    )
    assert publish_candidate(
        api,
        repo,
        coordination_ref=ref,
        expected_base_sha=token,
        owner_id="closer",
        candidate_sha=tombstone,
    ).acquired

    with pytest.raises(LinearizableLeaseError, match="FENCING_TOKEN_NOT_EXECUTABLE"):
        verify_fencing_token(
            api,
            repo,
            coordination_ref=ref,
            fencing_token_sha=tombstone,
            expected_decision_record_sha256="b" * 64,
            expected_effect_plan_sha256="c" * 64,
        )
