from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github" / "workflows" / "live-executor-takeover-lease-controller.yml"
FIXTURE = ROOT / ".github" / "workflows" / "live-executor-takeover-lease-fixture.yml"
EXECUTOR = ROOT / "effect_executor.py"


def test_controller_moves_ownership_across_distinct_jobs():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Worker A acquires lease then dies" in text
    assert "Worker B takes over expired lease" in text
    assert "Returned worker A is fenced out" in text
    assert "Worker B executes under epoch 2" in text
    assert "needs: worker-a" in text
    assert "needs: worker-b-lease" in text
    assert "needs: stale-worker-a" in text


def test_stale_worker_is_denied_before_worker_b_mutates_target():
    text = CONTROLLER.read_text(encoding="utf-8")

    stale_pos = text.index("Returned worker A attempts stale execution")
    b_effect_pos = text.index("Execute under current worker B lease")
    assert stale_pos < b_effect_pos
    assert "EXECUTION_LEASE_BLOCK: LEASE_SUPERSEDED:" in text
    assert 'test "$TRIGGERED" = "false"' in text
    assert 'test "$OWNER" = "worker-a"' in text
    assert 'test "$EPOCH" = "1"' in text


def test_current_worker_executes_with_epoch_two_and_persists_receipt():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "--owner worker-b" in text
    assert 'test "$OWNER" = "worker-b"' in text
    assert 'test "$EPOCH" = "2"' in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text
    assert "Persist authoritative worker B receipt" in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_effect_boundary_has_optional_lease_fence():
    text = EXECUTOR.read_text(encoding="utf-8")

    assert "INPUT_EXECUTION_LEASE_PATH" in text
    assert "INPUT_EXECUTION_LEASE_REGISTRY_DIR" in text
    assert "INPUT_EXECUTOR_ID" in text
    assert "verify_effect_ownership" in text
    assert "EXECUTION_LEASE_BLOCK" in text


def test_takeover_fixture_is_bounded_and_real():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 20" in text
