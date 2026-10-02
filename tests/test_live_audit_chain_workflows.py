from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / ".github" / "workflows" / "live-audit-chain-fixture.yml"
CONTROLLER = ROOT / ".github" / "workflows" / "live-audit-chain-controller.yml"


def test_live_fixture_is_bounded_to_one_synthetic_failure():
    text = FIXTURE.read_text(encoding="utf-8")

    assert 'name: Live Audit Chain Fixture' in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (28) Operation timed out" in text
    assert "sleep 15" in text
    assert "workflow_dispatch:" in text


def test_controller_governs_exact_fixture_run_and_reconciles_next_attempt():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert 'workflows: ["Live Audit Chain Fixture"]' in text
    assert "actions: write" in text
    assert "checks: read" in text
    assert "run-id: ${{ github.event.workflow_run.id }}" in text
    assert "auto-rerun: ${{ github.event.workflow_run.run_attempt == 1" in text
    assert 'test "$DECISION" = "ALLOW"' in text
    assert 'test "$EFFECT_OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$RERUN_TRIGGERED" = "true"' in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_fixture_only_auto_triggers_when_live_e2e_files_change():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "paths:" in text
    assert ".github/workflows/live-audit-chain-fixture.yml" in text
    assert ".github/workflows/live-audit-chain-controller.yml" in text
