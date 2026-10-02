from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github" / "workflows" / "live-lease-contention-controller.yml"
FIXTURE = ROOT / ".github" / "workflows" / "live-lease-contention-fixture.yml"
LEASE = ROOT / "execution_lease.py"


def test_two_claimants_derive_the_same_next_epoch_in_parallel_jobs():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Claimant B independently claims epoch 2" in text
    assert "Claimant C independently claims epoch 2" in text
    assert "needs: owner-a" in text
    assert "--owner claimant-b" in text
    assert "--owner claimant-c" in text
    assert 'test "$EPOCH" = "2"' in text


def test_same_epoch_conflict_is_proved_before_any_effect():
    text = CONTROLLER.read_text(encoding="utf-8")

    conflict_pos = text.index("Same-epoch contention fences both claimants")
    resolution_pos = text.index("Resolver D advances only after all epoch 2 claims expire")
    assert conflict_pos < resolution_pos
    assert "active same-epoch contention confirmed" in text
    assert "Claimant B attempts effect under conflicted epoch" in text
    assert "Claimant C attempts effect under conflicted epoch" in text
    assert "EXECUTION_LEASE_BLOCK: LEASE_EPOCH_CONFLICT:" in text
    assert 'test "$B_TRIGGERED" = "false"' in text
    assert 'test "$C_TRIGGERED" = "false"' in text


def test_resolution_waits_for_both_contenders_and_advances_epoch():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Wait for all contenders then resolve at epoch 3" in text
    assert "--contender" in text
    assert "--owner resolver-d" in text
    assert "--wait" in text
    assert 'test "$OWNER" = "resolver-d"' in text
    assert 'test "$EPOCH" = "3"' in text


def test_only_resolved_epoch_may_execute_and_reconcile():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Execute once after contention resolution" in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text
    assert "Persist authoritative resolved receipt" in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_execution_lease_supports_predecessor_set_binding():
    text = LEASE.read_text(encoding="utf-8")

    assert "previous_lease_set_sha256" in text
    assert "build_contention_resolution_lease" in text
    assert "LEASE_CONTENTION_ACTIVE" in text
    assert "LEASE_CONTENTION_BINDING_MISMATCH" in text


def test_fixture_is_bounded_to_one_rerun():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 20" in text
