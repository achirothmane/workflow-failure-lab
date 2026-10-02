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
