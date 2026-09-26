from __future__ import annotations

import json

import pytest

from evidence_artifact import (
    EvidenceArtifactError,
    evidence_sha256,
    read_evidence_artifact,
    write_evidence_artifact,
)


def _bundle() -> dict:
    return {
        "schema_version": "evidence-producer.ci.v1",
        "producer": {
            "name": "workflow-failure-lab",
            "mode": "deterministic",
            "policy_free": True,
        },
        "subject": {
            "type": "ci_workflow_run",
            "repository": "owner/repo",
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 99,
        },
        "observed_at": "2026-09-22T20:10:00Z",
        "observations": [],
        "derived": [],
        "inferred": [],
        "quality": {
            "status": "COMPLETE",
            "missing_sources": [],
            "contradictions": [],
        },
    }


def test_artifact_round_trip_is_canonical_and_hash_verified(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    bundle = _bundle()

    digest = write_evidence_artifact(path, bundle)

    assert digest == evidence_sha256(bundle)
    assert read_evidence_artifact(path, expected_sha256=digest) == bundle
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_artifact_tamper_is_detected_before_gate_use(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    digest = write_evidence_artifact(path, _bundle())

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["subject"]["run_id"] = 999
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(EvidenceArtifactError, match="SHA-256 mismatch"):
        read_evidence_artifact(path, expected_sha256=digest)
