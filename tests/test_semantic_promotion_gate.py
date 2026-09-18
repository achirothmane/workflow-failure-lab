from semantic_promotion_gate import (
    REASON_COMMAND_SOURCE_TEXT,
    REASON_GENERIC_CANCELLATION,
    REASON_GENERIC_RUNNER_WRAPPER,
    REASON_SUCCESSFUL_TEST_LINE,
    SEMANTIC_PROMOTION_BLOCKED,
    SEMANTIC_PROMOTION_ELIGIBLE,
    assess_semantic_promotion_signature,
)


def test_generic_runner_exit_wrapper_is_blocked():
    result = assess_semantic_promotion_signature(
        "##[error]process completed with exit code <n>."
    )

    assert result.status == SEMANTIC_PROMOTION_BLOCKED
    assert result.accepted_segments == ()
    assert result.reasons == (REASON_GENERIC_RUNNER_WRAPPER,)


def test_generic_cancellation_is_blocked():
    result = assess_semantic_promotion_signature(
        "##[error]the operation was canceled."
    )

    assert result.status == SEMANTIC_PROMOTION_BLOCKED
    assert result.reasons == (REASON_GENERIC_CANCELLATION,)


def test_successful_test_name_with_cannot_is_blocked():
    result = assess_semantic_promotion_signature(
        "test alt_registry::cannot_publish_to_crates_io_with_registry_dependency ... ok"
    )

    assert result.status == SEMANTIC_PROMOTION_BLOCKED
    assert result.reasons == (REASON_SUCCESSFUL_TEST_LINE,)


def test_command_source_text_is_not_promotable_failure_evidence():
    result = assess_semantic_promotion_signature(
        'printf "%s: command not found\\n" "$<n>" >&<n>'
    )

    assert result.status == SEMANTIC_PROMOTION_BLOCKED
    assert result.reasons == (REASON_COMMAND_SOURCE_TEXT,)


def test_specific_failure_semantics_are_eligible():
    result = assess_semantic_promotion_signature(
        "fatal: remote cache service unavailable"
    )

    assert result.status == SEMANTIC_PROMOTION_ELIGIBLE
    assert result.accepted_segments == (
        "fatal: remote cache service unavailable",
    )


def test_mixed_generic_wrapper_and_specific_failure_keeps_specific_evidence():
    result = assess_semantic_promotion_signature(
        "##[error]process completed with exit code <n>. | "
        "fatal: remote cache service unavailable"
    )

    assert result.status == SEMANTIC_PROMOTION_ELIGIBLE
    assert result.accepted_segments == (
        "fatal: remote cache service unavailable",
    )
    assert result.rejected_segments == (
        "##[error]process completed with exit code <n>.",
    )
    assert REASON_GENERIC_RUNNER_WRAPPER in result.reasons
