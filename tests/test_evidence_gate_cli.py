from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evidence_artifact import write_evidence_artifact


ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "evidence_gate_cli.py"


def _bundle() -> dict:
    subject = {
        "job_id": 42,
        "job_name": "unit-tests",
    }
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
        "observations": [
            {
                "kind": "OBSERVED",
                "source": "github-actions.job-log",
                "subject": subject,
                "detail": "curl: (28) operation timed out",
            }
        ],
        "derived": [
            {
                "kind": "DERIVED",
                "claim": "failure_category",
                "subject": subject,
                "value": "DEPENDENCY_NETWORK",
                "support": ["curl: (28) operation timed out"],
            },
            {
                "kind": "DERIVED",
                "claim": "classification_confidence",
                "subject": subject,
                "value": "high",
                "support": ["curl: (28) operation timed out"],
            },
            {
                "kind": "DERIVED",
                "claim": "execution_provenance_status",
                "subject": subject,
                "value": "CONFIRMED",
                "support": ["signal bound to failed step"],
            },
            {
                "kind": "DERIVED",
                "claim": "failure_step_status",
                "subject": subject,
                "value": "FAILURE_STEP_CONFIRMED",
                "support": ["failed step: Install dependencies"],
            },
            {
                "kind": "DERIVED",
                "claim": "side_effect_risk",
                "subject": subject,
                "value": False,
                "support": [],
            },
        ],
        "inferred": [],
        "quality": {
            "status": "COMPLETE",
            "missing_sources": [],
            "contradictions": [],
        },
    }


def _run_cli(path: Path, digest: str) -> dict:
    completed = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--evidence",
            str(path),
            "--expected-sha256",
            digest,
            "--max-attempts",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_gate_runs_in_separate_process_from_persisted_artifact(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    digest = write_evidence_artifact(path, _bundle())

    decision = _run_cli(path, digest)

    assert decision["decision"] == "ALLOW"
    assert decision["evidence_status"] == "SUFFICIENT"
    assert decision["evidence_bundle"]["subject"]["run_id"] == 123


def test_gate_process_fails_closed_if_artifact_changes_after_production(tmp_path) -> None:
    path = tmp_path / "evidence.json"
    digest = write_evidence_artifact(path, _bundle())

    changed = _bundle()
    changed["subject"]["head_sha"] = "tampered"
    write_evidence_artifact(path, changed)

    decision = _run_cli(path, digest)

    assert decision["decision"] == "BLOCK"
    assert decision["evidence_status"] == "UNKNOWN"
    assert "SHA-256 mismatch" in decision["reasons"][0]
    assert decision["evidence_bundle"] is None
