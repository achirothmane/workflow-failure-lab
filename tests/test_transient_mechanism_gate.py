from transient_mechanism_gate import (
    MECHANISM_DETERMINISTIC,
    MECHANISM_TRANSIENT_SUPPORTED,
    MECHANISM_UNPROVEN,
    REASON_AUTH_PERMISSION,
    REASON_COMMAND_CONFIG,
    REASON_CONNECTION_RESET,
    REASON_NO_TRANSIENT_MECHANISM,
    REASON_TEST_BUILD,
    assess_transient_mechanism,
)


def test_connection_reset_is_positive_transient_mechanism():
    result = assess_transient_mechanism(
        "fatal: connection reset by peer while reading remote cache",
        ("AMBIGUOUS_OPERATIONAL",),
    )

    assert result.status == MECHANISM_TRANSIENT_SUPPORTED
    assert REASON_CONNECTION_RESET in result.reasons
    assert result.transient_evidence


def test_command_config_without_transient_evidence_is_deterministic():
    result = assess_transient_mechanism(
        "could not find file: /workspace/uv.toml",
        ("COMMAND_CONFIG",),
    )

    assert result.status == MECHANISM_DETERMINISTIC
    assert result.reasons == (REASON_COMMAND_CONFIG,)


def test_auth_without_transient_evidence_is_deterministic():
    result = assess_transient_mechanism(
        "error: permission denied while reading deployment secret",
        ("AUTH_PERMISSION",),
    )

    assert result.status == MECHANISM_DETERMINISTIC
    assert result.reasons == (REASON_AUTH_PERMISSION,)


def test_build_failure_without_transient_evidence_is_deterministic():
    result = assess_transient_mechanism(
        "error: compilation error in module",
        ("TEST_BUILD",),
    )

    assert result.status == MECHANISM_DETERMINISTIC
    assert result.reasons == (REASON_TEST_BUILD,)


def test_ambiguous_specific_failure_without_transient_mechanism_is_unproven():
    result = assess_transient_mechanism(
        "fatal: remote cache checksum mismatch",
        ("AMBIGUOUS_OPERATIONAL",),
    )

    assert result.status == MECHANISM_UNPROVEN
    assert result.reasons == (REASON_NO_TRANSIENT_MECHANISM,)


def test_explicit_transient_evidence_can_override_deterministic_diagnostic_family():
    result = assess_transient_mechanism(
        "error: command failed after connection reset by peer",
        ("COMMAND_CONFIG",),
    )

    assert result.status == MECHANISM_TRANSIENT_SUPPORTED
    assert REASON_CONNECTION_RESET in result.reasons
    assert result.deterministic_causes == ("COMMAND_CONFIG",)
