from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "e2e" / "fault_injected_effect_executor.py"
WAITER = ROOT / "e2e" / "wait_for_run_attempt.py"
CONTROLLER = ROOT / ".github" / "workflows" / "live-crash-window-controller.yml"
BEFORE = ROOT / ".github" / "workflows" / "live-crash-before-effect-fixture.yml"
AFTER = ROOT / ".github" / "workflows" / "live-crash-after-effect-fixture.yml"
UNKNOWN = ROOT / ".github" / "workflows" / "live-ambiguous-transport-fixture.yml"


def test_fault_injector_has_all_three_effect_windows():
    text = HARNESS.read_text(encoding="utf-8")

    assert 'mode == "crash-before-dispatch"' in text
    assert 'mode == "crash-after-dispatch"' in text
    assert 'mode == "timeout-after-dispatch"' in text
    assert "os._exit(86)" in text
    assert "os._exit(87)" in text
    assert "original(self, repo, run_id)" in text
    assert "synthetic transport timeout after dispatch" in text


def test_waiter_observes_real_github_run_attempt():
    text = WAITER.read_text(encoding="utf-8")

    assert "TARGET_ATTEMPT" in text
    assert "/actions/runs/{run_id}" in text
    assert 'payload.get("run_attempt")' in text


def test_crash_before_requires_takeover_to_execute_once():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Crash immediately before dispatch" in text
    assert "Take over the same persisted plan" in text
    assert 'test "$CRASH_OUTCOME" = "failure"' in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text
    assert 'test "$STATUS" = "RECOVERED_AFTER_RERUN"' in text


def test_crash_after_rejects_stale_takeover_and_loses_original_receipt():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Dispatch then crash before receipt" in text
    assert "Take over with the stale persisted plan" in text
    assert "crash-after-takeover.eba-receipt.json" in text
    assert 'test "$OUTCOME" = "NOT_EXECUTED"' in text
    assert 'test "$TRIGGERED" = "false"' in text
    assert "RERUN_SCOPE_CHANGED:*" in text
    assert 'test "$STATUS" = "SUBSEQUENT_ATTEMPT_EXTERNAL_OR_UNKNOWN"' in text


def test_ambiguous_transport_persists_unknown_and_blocks_duplicate():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Dispatch then surface transport ambiguity" in text
    assert 'test "$OUTCOME" = "UNKNOWN"' in text
    assert "RERUN_DISPATCH_UNKNOWN:*" in text
    assert "Persist UNKNOWN execution receipt" in text
    assert "Retry the ambiguous effect only after state revalidation" in text
    assert "ambiguous-takeover.eba-receipt.json" in text
    assert 'test "$STATUS" = "SUBSEQUENT_ATTEMPT_EXTERNAL_OR_UNKNOWN"' in text


def test_all_crash_window_fixtures_are_bounded_to_two_attempts():
    for fixture in (BEFORE, AFTER, UNKNOWN):
        text = fixture.read_text(encoding="utf-8")
        assert "branches: [main]" in text
        assert "workflow_dispatch:" in text
        assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
        assert "curl: (6) Could not resolve host" in text
        assert "tests/test_live_crash_window_workflows.py" in text
