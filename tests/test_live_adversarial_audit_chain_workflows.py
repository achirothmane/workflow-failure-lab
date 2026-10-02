from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REPLAY_FIXTURE = ROOT / ".github" / "workflows" / "live-audit-chain-replay-fixture.yml"
REPLAY_CONTROLLER = ROOT / ".github" / "workflows" / "live-audit-chain-replay-controller.yml"
LOSS_FIXTURE = ROOT / ".github" / "workflows" / "live-audit-chain-receipt-loss-fixture.yml"
LOSS_CONTROLLER = ROOT / ".github" / "workflows" / "live-audit-chain-receipt-loss-controller.yml"


def test_replay_fixture_is_bounded_and_keeps_attempt_two_alive():
    text = REPLAY_FIXTURE.read_text(encoding="utf-8")

    assert 'name: Live Audit Chain Replay Fixture' in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 25" in text
    assert "workflow_dispatch:" in text


def test_replay_controller_persists_primary_receipt_then_replays_same_plan():
    text = REPLAY_CONTROLLER.read_text(encoding="utf-8")

    assert 'workflows: ["Live Audit Chain Replay Fixture"]' in text
    assert "actions: write" in text
    assert "INPUT_DEFER_EFFECT: 'true'" in text
    assert "Persist confirmed execution receipt" in text
    assert "Wait for target state to advance to attempt 2" in text
    assert "Replay the same stale admitted plan" in text
    assert "${{ steps.gate.outputs.effect-plan-path }}" in text
    assert "${{ runner.temp }}/duplicate-replay.eba-receipt.json" in text
    assert 'test "$OUTCOME" = "NOT_EXECUTED"' in text
    assert 'test "$TRIGGERED" = "false"' in text
    assert "RERUN_SCOPE_CHANGED:*" in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_receipt_loss_fixture_is_bounded():
    text = LOSS_FIXTURE.read_text(encoding="utf-8")

    assert 'name: Live Audit Chain Receipt Loss Fixture' in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 10" in text


def test_receipt_loss_controller_never_uploads_attempt_one_receipt():
    text = LOSS_CONTROLLER.read_text(encoding="utf-8")

    assert 'workflows: ["Live Audit Chain Receipt Loss Fixture"]' in text
    assert "Persist pre-effect audit trail" in text
    assert "Execute admitted effect but lose the receipt" in text
    assert "Execution receipt intentionally not uploaded" in text
    assert "name: ${{ steps.gate.outputs.decision-record-artifact-name }}-receipt" not in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text


def test_missing_receipt_reconciliation_fails_closed_on_attribution():
    text = LOSS_CONTROLLER.read_text(encoding="utf-8")

    assert "Reconcile next attempt without a retained receipt" in text
    assert 'test "$STATUS" = "SUBSEQUENT_ATTEMPT_EXTERNAL_OR_UNKNOWN"' in text
    assert 'test -n "$OUTCOME_PATH"' in text
    assert 'test -n "$RECONCILIATION_PATH"' in text


def test_adversarial_live_scenarios_only_auto_trigger_from_main_file_changes():
    for fixture in (REPLAY_FIXTURE, LOSS_FIXTURE):
        text = fixture.read_text(encoding="utf-8")
        assert "branches: [main]" in text
        assert "paths:" in text
        assert "tests/test_live_adversarial_audit_chain_workflows.py" in text
