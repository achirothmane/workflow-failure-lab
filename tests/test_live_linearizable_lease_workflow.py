from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github" / "workflows" / "live-linearizable-lease-controller.yml"
FIXTURE = ROOT / ".github" / "workflows" / "live-linearizable-lease-fixture.yml"
EXECUTOR = ROOT / "effect_executor.py"
LEASE = ROOT / "linearizable_lease.py"


def test_prepared_candidates_share_one_base_before_publish_race():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Prepare claimant B sibling candidate" in text
    assert "Prepare claimant C sibling candidate" in text
    assert "needs: [seed, prepare-b, prepare-c]" in text
    assert "--base-sha" in text
    assert 'test "$PREPARED_B" != "$PREPARED_C"' in text


def test_publish_race_requires_exactly_one_winner():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Claimant B CAS publishes sibling" in text
    assert "Claimant C CAS publishes sibling" in text
    assert "Assert one winner and one fenced sibling" in text
    assert "CAS_ACQUIRED" in text
    assert "CAS_LOST:" in text
    assert "CAS must have exactly one winner" in text


def test_loser_is_fenced_before_winner_mutates_target():
    text = CONTROLLER.read_text(encoding="utf-8")

    loser_pos = text.index("Losing claimant is fenced before target mutation")
    winner_pos = text.index("CAS winner executes exactly one effect")
    assert loser_pos < winner_pos
    assert "needs: [seed, arbitrate, loser-fenced]" in text
    assert "LINEARIZABLE_FENCE_BLOCK: FENCING_TOKEN_STALE:" in text
    assert 'test "$TRIGGERED" = "false"' in text


def test_winner_token_is_live_effect_authority():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Present winning fencing token at effect boundary" in text
    assert "INPUT_LINEARIZABLE_COORDINATION_REF" in text
    assert "INPUT_LINEARIZABLE_FENCING_TOKEN_SHA" in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_effect_executor_verifies_live_ref_before_mutation():
    text = EXECUTOR.read_text(encoding="utf-8")

    assert "INPUT_LINEARIZABLE_COORDINATION_REF" in text
    assert "INPUT_LINEARIZABLE_FENCING_TOKEN_SHA" in text
    assert "verify_fencing_token" in text
    assert "LINEARIZABLE_FENCE_BLOCK" in text


def test_coordination_primitive_uses_non_force_git_ref_update():
    text = LEASE.read_text(encoding="utf-8")

    assert '"PATCH"' in text
    assert '"force": False' in text
    assert "CAS_ACQUIRED" in text
    assert "CAS_LOST:" in text
    assert "FENCING_TOKEN_STALE" in text


def test_fixture_is_bounded_to_one_rerun():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 20" in text
