from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from decision_history import (
    DecisionHistoryError,
    decision_artifact_prefix,
    download_prior_audit_trail,
    find_previous_decision_artifact,
)
from decision_record import build_decision_record, seal_decision_record
from eba_integration_contract import RECEIPT_KIND, canonical_json_bytes


def _decision_record(*, attempt: int = 1) -> dict:
    record = build_decision_record(
        evidence_decision={
            "decision": "ALLOW",
            "evidence_status": "SUFFICIENT",
            "reasons": ["safe transient failure"],
            "scope": {
                "repository": "owner/repo",
                "run_id": 123,
                "run_attempt": attempt,
                "head_sha": "abc123",
                "workflow_id": 99,
            },
        },
        evidence_bundle_sha256="a" * 64,
        policy_ref="ci-retry-gate.production.v1",
        authorization_path="POLICY",
        next_action="RERUN_ALLOWED",
        identities={
            "decision_engine": {
                "raw": "achirothmane/workflow-failure-lab",
                "identity_type": "unknown",
            }
        },
        event_id=f"evt-{attempt}",
        recorded_at=f"2026-10-02T0{attempt}:00:00Z",
    )
    return seal_decision_record(record)


def _receipt(*, outcome: str = "SUCCEEDED") -> dict:
    receipt = {
        "kind": RECEIPT_KIND,
        "outcome": outcome,
        "decision_ref": "decision-1",
    }
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    receipt["integrity"] = {"algorithm": "sha256", "digest": digest}
    return receipt


def _zip_payload(decision: dict, receipt: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "owner-repo-run-123-attempt-1.decision-record.json",
            json.dumps(decision),
        )
        if receipt is not None:
            archive.writestr(
                "owner-repo-run-123-attempt-1.eba-receipt.json",
                json.dumps(receipt),
            )
    return buffer.getvalue()


class FakeAPI:
    def __init__(self, artifacts: list[dict], payloads: dict[int, bytes]):
        self.artifacts = artifacts
        self.payloads = payloads

    def request(self, method: str, path: str):
        assert method == "GET"
        return {"artifacts": self.artifacts}

    def request_bytes(self, method: str, path: str) -> bytes:
        artifact_id = int(path.split("/")[-2])
        return self.payloads[artifact_id]


def test_unique_previous_artifact_is_discovered_and_digest_anchored() -> None:
    decision = _decision_record()
    name = decision_artifact_prefix(run_id=123, run_attempt=1) + decision["record_sha256"]
    api = FakeAPI(
        artifacts=[
            {
                "id": 7,
                "name": name,
                "expired": False,
                "workflow_run": {"id": 9001},
            }
        ],
        payloads={7: _zip_payload(decision, _receipt())},
    )

    ref = find_previous_decision_artifact(
        api,
        "owner/repo",
        run_id=123,
        current_attempt=2,
    )
    assert ref is not None
    assert ref.digest_anchor == decision["record_sha256"]

    trail = download_prior_audit_trail(api, "owner/repo", ref)
    assert trail.decision_record["event_id"] == "evt-1"
    assert trail.execution_receipt["outcome"] == "SUCCEEDED"


def test_multiple_matching_prior_artifacts_are_ambiguous() -> None:
    decision = _decision_record()
    prefix = decision_artifact_prefix(run_id=123, run_attempt=1)
    api = FakeAPI(
        artifacts=[
            {"id": 7, "name": prefix + decision["record_sha256"], "expired": False},
            {"id": 8, "name": prefix + ("b" * 64), "expired": False},
        ],
        payloads={},
    )

    with pytest.raises(DecisionHistoryError, match="ambiguous prior decision history"):
        find_previous_decision_artifact(
            api,
            "owner/repo",
            run_id=123,
            current_attempt=2,
        )


def test_artifact_name_anchor_rejects_resealed_rewrite() -> None:
    original = _decision_record()
    original_name = (
        decision_artifact_prefix(run_id=123, run_attempt=1)
        + original["record_sha256"]
    )

    rewritten = dict(original)
    rewritten["decision"] = "BLOCK"
    rewritten.pop("record_sha256")
    rewritten = seal_decision_record(rewritten)

    api = FakeAPI(
        artifacts=[{"id": 9, "name": original_name, "expired": False}],
        payloads={9: _zip_payload(rewritten)},
    )
    ref = find_previous_decision_artifact(
        api,
        "owner/repo",
        run_id=123,
        current_attempt=2,
    )
    assert ref is not None

    with pytest.raises(DecisionHistoryError, match="artifact-name anchor"):
        download_prior_audit_trail(api, "owner/repo", ref)


def test_separate_post_effect_receipt_artifact_is_discovered() -> None:
    decision = _decision_record()
    decision_name = (
        decision_artifact_prefix(run_id=123, run_attempt=1)
        + decision["record_sha256"]
    )
    receipt_name = decision_name + "-receipt"

    decision_zip = _zip_payload(decision, None)
    receipt_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(receipt_zip_buffer, "w") as archive:
        archive.writestr(
            "owner-repo-run-123-attempt-1.eba-receipt.json",
            json.dumps(_receipt()),
        )

    api = FakeAPI(
        artifacts=[
            {"id": 10, "name": decision_name, "expired": False},
            {"id": 11, "name": receipt_name, "expired": False},
        ],
        payloads={
            10: decision_zip,
            11: receipt_zip_buffer.getvalue(),
        },
    )

    ref = find_previous_decision_artifact(
        api,
        "owner/repo",
        run_id=123,
        current_attempt=2,
    )
    assert ref is not None

    trail = download_prior_audit_trail(api, "owner/repo", ref)
    assert trail.execution_receipt is not None
    assert trail.execution_receipt["outcome"] == "SUCCEEDED"
