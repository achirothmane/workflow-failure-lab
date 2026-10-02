from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github" / "workflows" / "live-aba-token-resurrection-controller.yml"
FIXTURE = ROOT / ".github" / "workflows" / "live-aba-token-resurrection-fixture.yml"
EXECUTOR = ROOT / "effect_executor.py"
LEASE = ROOT / "linearizable_lease.py"


def test_lineage_advances_t1_to_t2_before_attack():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Acquire token T1 on both records" in text
    assert "Advance lineage to token T2" in text
    assert "Publish T1 to witness" in text
    assert "Advance witness to T2" in text


def test_non_force_rollback_is_rejected_before_delete_recreate_attack():
    text = CONTROLLER.read_text(encoding="utf-8")

    rollback = text.index("Non-force rollback to T1 is rejected")
    resurrect = text.index("Simulate delete and recreate ABA at T1")
    assert rollback < resurrect
    assert "CAS_LOST:" in text
    assert 'test "$OBSERVED" = "${{ needs.token2.outputs.token }}"' in text


def test_delete_recreate_attack_leaves_witness_at_t2():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Delete only the mutable coordination record" in text
    assert "Recreate coordination at superseded T1" in text
    assert "Read durable witness high-water mark" in text
    assert 'test "$COORD" = "${{ needs.token1.outputs.token }}"' in text
    assert 'test "$WITNESS" = "${{ needs.token2.outputs.token }}"' in text


def test_resurrected_t1_is_fenced_before_effect():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Resurrected T1 is fenced by witness" in text
    assert "INPUT_LINEARIZABLE_WITNESS_REF" in text
    assert "ABA_WITNESS_MISMATCH:" in text
    assert 'test "$OUTCOME" = "NOT_EXECUTED"' in text
    assert 'test "$TRIGGERED" = "false"' in text


def test_recovery_advances_to_t3_then_executes_once():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Advance beyond ABA and execute T3 once" in text
    assert "Prepare T3 from witnessed T2 lineage" in text
    assert "Fast-forward resurrected coordination past T2 to T3" in text
    assert "Advance witness from T2 to T3" in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text


def test_closed_tombstone_remains_non_executable_and_is_retained():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Prepare non-executable closed tombstone T4" in text
    assert "Present closed T4 as if it were executable" in text
    assert "FENCING_TOKEN_NOT_EXECUTABLE:" in text
    assert "Preserve tombstoned refs as durable high-water marks" in text
    assert "intentionally retained" in text


def test_effect_boundary_verifies_witness_and_exact_contract_binding():
    text = EXECUTOR.read_text(encoding="utf-8")

    assert "INPUT_LINEARIZABLE_WITNESS_REF" in text
    assert "expected_decision_record_sha256=decision_record_sha" in text
    assert "expected_effect_plan_sha256=plan_sha" in text


def test_lease_primitive_contains_aba_and_tombstone_guards():
    text = LEASE.read_text(encoding="utf-8")

    assert "ABA_WITNESS_MISMATCH" in text
    assert "FENCING_TOKEN_NOT_EXECUTABLE" in text
    assert "FENCING_TOKEN_DECISION_BINDING_MISMATCH" in text
    assert "FENCING_TOKEN_EFFECT_PLAN_BINDING_MISMATCH" in text
    assert "ci-retry-gate-linearizable-lease-closed" in text


def test_fixture_is_bounded_to_one_rerun():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 20" in text
