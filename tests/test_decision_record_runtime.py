from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_decision_record_is_persisted_before_auto_rerun_effect_boundary() -> None:
    source = (ROOT / "ci_retry_gate.py").read_text(encoding="utf-8")

    write_index = source.index("decision_record_sha256 = write_decision_record(")
    rerun_index = source.index("api.rerun_failed_jobs(repo, run_id)")

    assert write_index < rerun_index


def test_action_uploads_decision_record_as_a_github_artifact() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert "Upload decision audit trail" in action
    assert "actions/upload-artifact@v4" in action
    assert "steps.gate.outputs.decision-record-path" in action
    assert "steps.gate.outputs.decision-record-artifact-name" in action


def test_audit_artifact_retains_receipt_and_optional_t2_records() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert "steps.gate.outputs.eba-receipt-path" in action
    assert "steps.gate.outputs.outcome-record-path" in action
    assert "steps.gate.outputs.reconciliation-record-path" in action


def test_new_artifact_name_anchors_full_decision_digest() -> None:
    source = (ROOT / "ci_retry_gate.py").read_text(encoding="utf-8")

    assert 'f"{decision_record_sha256}"' in source
    assert "decision_record_sha256[:12]" not in source


def test_prior_history_is_not_an_authorization_source() -> None:
    source = (ROOT / "ci_retry_gate.py").read_text(encoding="utf-8")

    discovery_index = source.index("find_previous_decision_artifact(")
    gate_index = source.index("evidence_decision = _run_evidence_gate_process(")
    assert discovery_index < gate_index
    assert "History failure is non-authorizing" not in source
    assert "Audit history is observation-only" in source
