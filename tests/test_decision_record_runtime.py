from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_decision_record_is_persisted_before_direct_auto_rerun_effect_boundary() -> None:
    source = (ROOT / "ci_retry_gate.py").read_text(encoding="utf-8")

    write_index = source.index("decision_record_sha256 = write_decision_record(")
    rerun_index = source.index("api.rerun_failed_jobs(repo, run_id)")

    assert write_index < rerun_index


def test_composite_uploads_pre_effect_audit_before_executor() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    upload_index = action.index("Upload pre-effect decision audit trail")
    effect_index = action.index("Execute admitted rerun after durable audit upload")

    assert "actions/upload-artifact@v4" in action
    assert "steps.gate.outputs.decision-record-path" in action
    assert "steps.gate.outputs.effect-plan-path" in action
    assert upload_index < effect_index


def test_execution_receipt_is_uploaded_only_after_effect_executor() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    pre_effect_start = action.index("Upload pre-effect decision audit trail")
    effect_index = action.index("Execute admitted rerun after durable audit upload")
    receipt_upload_index = action.index("Upload execution receipt")
    pre_effect_block = action[pre_effect_start:effect_index]

    assert "steps.gate.outputs.eba-receipt-path" not in pre_effect_block
    assert effect_index < receipt_upload_index
    assert "steps.effect.outputs.eba-receipt-path" in action


def test_audit_artifact_retains_optional_t2_records() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

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
    assert "Audit history is observation-only" in source


def test_composite_gate_defers_effect_to_separate_executor() -> None:
    action = (ROOT / "action.yml").read_text(encoding="utf-8")

    assert "INPUT_DEFER_EFFECT: 'true'" in action
    assert 'python3 "$GITHUB_ACTION_PATH/effect_executor.py"' in action
    assert "value: ${{ steps.effect.outputs.rerun-triggered }}" in action
    assert "value: ${{ steps.effect.outputs.eba-receipt-sha256 }}" in action
