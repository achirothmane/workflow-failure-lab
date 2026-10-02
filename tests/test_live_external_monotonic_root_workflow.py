from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / ".github" / "workflows" / "live-external-monotonic-root-controller.yml"
FIXTURE = ROOT / ".github" / "workflows" / "live-external-monotonic-root-fixture.yml"
EXECUTOR = ROOT / "effect_executor.py"
ROOT_MODULE = ROOT / "external_monotonic_root.py"


def test_controller_creates_public_sigstore_high_water_marks():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "id-token: write" in text
    assert "attestations: write" in text
    assert "artifact-metadata: write" in text
    assert "uses: actions/attest@v4" in text
    assert "Attest T2 root into Sigstore transparency log" in text
    assert "Attest CLOSED T4 high-water mark into Sigstore" in text
    assert "root-anchor-path" in text
    assert "--anchor" in text


def test_attack_rewinds_both_local_records_not_just_one():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Compromise both local records back to T1" in text
    assert "Delete mutable coordination and local witness" in text
    assert "Recreate both local records at superseded T1" in text
    assert 'test "$COORD" = "${{ needs.establish-t2.outputs.token1 }}"' in text
    assert 'test "$WITNESS" = "${{ needs.establish-t2.outputs.token1 }}"' in text


def test_external_root_fences_t1_after_double_local_compromise():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "External root fences T1 despite double local compromise" in text
    assert "INPUT_EXTERNAL_MONOTONIC_ROOT_RECORD_PATH" in text
    assert "INPUT_EXTERNAL_MONOTONIC_ROOT_ANCHOR_PATH" in text
    assert "INPUT_EXTERNAL_MONOTONIC_ROOT_BUNDLE_PATH" in text
    assert "INPUT_EXTERNAL_MONOTONIC_ROOT_SIGNER_WORKFLOW" in text
    assert "TOKEN_BELOW_EXTERNAL_MONOTONIC_ROOT:" in text
    assert 'test "$TRIGGERED" = "false"' in text


def test_descendant_t3_may_execute_above_t2_root():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Prepare T3 from externally witnessed T2 lineage" in text
    assert "Execute T3 only because it descends from external T2 root" in text
    assert 'test "$OUTCOME" = "SUCCEEDED"' in text
    assert 'test "$TRIGGERED" = "true"' in text
    assert 'test "$ROOT_EPOCH" = "2"' in text


def test_closed_t4_root_blocks_resurrection_of_previous_executable_t3():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Build CLOSED T4 external root record" in text
    assert "--state CLOSED" in text
    assert "Compromise both local records back to executable T3" in text
    assert "CLOSED external root prevents T3 resurrection" in text
    assert "Restore local records to CLOSED T4" in text


def test_valid_old_signed_root_is_rejected_after_closed_epoch_exists():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert "Old signed T2 root cannot override CLOSED T4" in text
    assert "Replay authentic old T2 root and bundle at Effect boundary" in text
    assert "STALE_EXTERNAL_ROOT_ATTESTATION: supplied_epoch=2 latest_epoch=4" in text
    assert "valid old signature cannot resurrect T2 authority" in text
    assert 'test "$TRIGGERED" = "false"' in text


def test_t2_and_t4_attest_the_same_stable_decision_anchor():
    text = CONTROLLER.read_text(encoding="utf-8")

    assert 'subject-path: ${{ steps.root.outputs.root-anchor-path }}' in text
    assert 'subject-path: ${{ steps.closed-root.outputs.root-anchor-path }}' in text
    assert 'root-t2/root-anchor.json' in text
    assert 'root-t4/root-anchor.json' in text


def test_effect_boundary_verifies_external_root_before_mutation():
    text = EXECUTOR.read_text(encoding="utf-8")

    external = text.index("verify_external_monotonic_root")
    rerun = text.index("api.rerun_failed_jobs")
    assert external < rerun
    assert "EXTERNAL_MONOTONIC_ROOT_BLOCK" in text
    assert "external-monotonic-root-enforced" in text


def test_external_root_verifier_checks_sigstore_and_git_ancestry():
    text = ROOT_MODULE.read_text(encoding="utf-8")

    assert '"gh"' in text
    assert '"attestation"' in text
    assert '"verify"' in text
    assert "--bundle" in text
    assert "--signer-workflow" in text
    assert '"api"' in text
    assert "/attestations/sha256:" in text
    assert "per_page=" in text
    assert "STALE_EXTERNAL_ROOT_ATTESTATION" in text
    assert "EXTERNAL_ROOT_FORK_AT_MAX_EPOCH" in text
    assert "--deny-self-hosted-runners" in text
    assert "/compare/{root}...{presented}" in text
    assert "TOKEN_BELOW_EXTERNAL_MONOTONIC_ROOT" in text


def test_fixture_is_bounded_to_one_rerun():
    text = FIXTURE.read_text(encoding="utf-8")

    assert "branches: [main]" in text
    assert "workflow_dispatch:" in text
    assert 'GITHUB_RUN_ATTEMPT}" = "1"' in text
    assert "curl: (6) Could not resolve host" in text
    assert "sleep 20" in text
