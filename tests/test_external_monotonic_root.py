from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from external_monotonic_root import (
    ExternalMonotonicRootError,
    build_root_record,
    read_root_record,
    root_record_digest,
    verify_external_monotonic_root,
    verify_root_binding,
    verify_sigstore_attestation,
    verify_token_not_below_root,
    write_root_record,
)


class FakeGitHubAPI:
    def __init__(self, *, status: str, ahead_by: int, behind_by: int):
        self.status = status
        self.ahead_by = ahead_by
        self.behind_by = behind_by
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, payload=None, accept="application/vnd.github+json"):
        del payload, accept
        self.calls.append((method, path))
        return {
            "status": self.status,
            "ahead_by": self.ahead_by,
            "behind_by": self.behind_by,
        }


def _record(*, token: str = "a" * 40, epoch: int = 2, state: str = "EXECUTABLE"):
    return build_root_record(
        repository="owner/repo",
        run_id=123,
        epoch=epoch,
        fencing_token_sha=token,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
        lifecycle_state=state,
    )


def test_root_record_is_digest_sealed_and_bound_to_effect(tmp_path: Path):
    record = _record()
    path = tmp_path / "root.json"
    digest = write_root_record(path, record)

    loaded = read_root_record(path)
    assert digest == root_record_digest(loaded)
    verify_root_binding(
        loaded,
        repository="owner/repo",
        run_id=123,
        decision_record_sha256="b" * 64,
        effect_plan_sha256="c" * 64,
    )

    loaded["epoch"] = 3
    path.write_text(json.dumps(loaded), encoding="utf-8")
    with pytest.raises(ExternalMonotonicRootError, match="SHA-256 mismatch"):
        read_root_record(path)


def test_root_binding_rejects_wrong_effect_plan():
    record = _record()

    with pytest.raises(
        ExternalMonotonicRootError,
        match="EXTERNAL_ROOT_EFFECT_PLAN_BINDING_MISMATCH",
    ):
        verify_root_binding(
            record,
            repository="owner/repo",
            run_id=123,
            decision_record_sha256="b" * 64,
            effect_plan_sha256="d" * 64,
        )


def test_presented_descendant_is_allowed():
    api = FakeGitHubAPI(status="ahead", ahead_by=1, behind_by=0)

    verify_token_not_below_root(
        api,
        "owner/repo",
        root_token_sha="a" * 40,
        presented_token_sha="d" * 40,
    )

    assert api.calls == [
        ("GET", f"/repos/owner/repo/compare/{'a' * 40}...{'d' * 40}")
    ]


@pytest.mark.parametrize(
    ("status", "ahead_by", "behind_by"),
    [
        ("behind", 0, 1),
        ("diverged", 1, 1),
        ("identical", 0, 0),
    ],
)
def test_presented_non_descendant_is_denied_when_sha_differs(status, ahead_by, behind_by):
    api = FakeGitHubAPI(
        status=status,
        ahead_by=ahead_by,
        behind_by=behind_by,
    )

    with pytest.raises(
        ExternalMonotonicRootError,
        match="TOKEN_BELOW_EXTERNAL_MONOTONIC_ROOT",
    ):
        verify_token_not_below_root(
            api,
            "owner/repo",
            root_token_sha="a" * 40,
            presented_token_sha="d" * 40,
        )


def test_sigstore_verifier_invocation_is_fail_closed(tmp_path: Path, monkeypatch):
    record_path = tmp_path / "root.json"
    bundle_path = tmp_path / "bundle.json"
    record_path.write_text("{}\n", encoding="utf-8")
    bundle_path.write_text("{}\n", encoding="utf-8")

    def fake_run(command, **kwargs):
        assert command[:3] == ["gh", "attestation", "verify"]
        assert "--bundle" in command
        assert "--signer-workflow" in command
        assert "--deny-self-hosted-runners" in command
        assert kwargs["timeout"] == 60
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="signature mismatch",
        )

    monkeypatch.setattr("external_monotonic_root.subprocess.run", fake_run)

    with pytest.raises(
        ExternalMonotonicRootError,
        match="SIGSTORE_ATTESTATION_INVALID",
    ):
        verify_sigstore_attestation(
            root_record_path=record_path,
            bundle_path=bundle_path,
            repository="owner/repo",
            signer_workflow="owner/repo/.github/workflows/root.yml",
        )


def test_external_root_rejects_token_below_attested_high_water_mark(
    tmp_path: Path,
    monkeypatch,
):
    record = _record(token="2" * 40, epoch=2)
    record_path = tmp_path / "root.json"
    bundle_path = tmp_path / "bundle.json"
    write_root_record(record_path, record)
    bundle_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "external_monotonic_root.verify_sigstore_attestation",
        lambda **kwargs: None,
    )
    api = FakeGitHubAPI(status="behind", ahead_by=0, behind_by=1)

    with pytest.raises(
        ExternalMonotonicRootError,
        match="TOKEN_BELOW_EXTERNAL_MONOTONIC_ROOT",
    ):
        verify_external_monotonic_root(
            api,
            "owner/repo",
            root_record_path=record_path,
            attestation_bundle_path=bundle_path,
            signer_workflow="owner/repo/.github/workflows/root.yml",
            predicate_type="https://example.test/root/v1",
            presented_token_sha="1" * 40,
            run_id=123,
            decision_record_sha256="b" * 64,
            effect_plan_sha256="c" * 64,
        )


@pytest.mark.parametrize("presented", ["3" * 40, "4" * 40, "5" * 40])
def test_closed_root_is_terminal_even_for_equal_or_descendant_tokens(
    tmp_path: Path,
    monkeypatch,
    presented: str,
):
    record = _record(token="4" * 40, epoch=4, state="CLOSED")
    record_path = tmp_path / "root.json"
    bundle_path = tmp_path / "bundle.json"
    write_root_record(record_path, record)
    bundle_path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        "external_monotonic_root.verify_sigstore_attestation",
        lambda **kwargs: None,
    )
    api = FakeGitHubAPI(status="ahead", ahead_by=1, behind_by=0)

    with pytest.raises(
        ExternalMonotonicRootError,
        match="EXTERNAL_ROOT_CLOSED",
    ):
        verify_external_monotonic_root(
            api,
            "owner/repo",
            root_record_path=record_path,
            attestation_bundle_path=bundle_path,
            signer_workflow="owner/repo/.github/workflows/root.yml",
            predicate_type="https://example.test/root/v1",
            presented_token_sha=presented,
            run_id=123,
            decision_record_sha256="b" * 64,
            effect_plan_sha256="c" * 64,
        )

    assert api.calls == []
