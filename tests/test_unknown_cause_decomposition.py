from unknown_cause_decomposition import (
    CAUSE_AMBIGUOUS_OPERATIONAL,
    CAUSE_AUTH_PERMISSION,
    CAUSE_COMMAND_CONFIG,
    CAUSE_GIT_VCS,
    CAUSE_NO_STABLE_ERROR_EVIDENCE,
    CAUSE_PACKAGE_TOOL,
    CAUSE_TEST_BUILD,
    CAUSE_TOOL_ACTION_SPECIFIC,
    decompose_unknown_cause,
)


def test_unknown_cause_no_stable_error_evidence():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z setup complete\n"
        "2026-09-18T01:00:01Z running checks\n"
    )
    assert result.cause == CAUSE_NO_STABLE_ERROR_EVIDENCE
    assert result.evidence == ()


def test_unknown_cause_auth_permission():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: permission denied while reading secret\n"
    )
    assert result.cause == CAUSE_AUTH_PERMISSION


def test_unknown_cause_git_vcs():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z error: failed to push some refs to 'origin'\n"
        "2026-09-18T01:00:01Z fatal: non-fast-forward update rejected\n"
    )
    assert result.cause == CAUSE_GIT_VCS


def test_unknown_cause_command_config():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: command not found: frobnicate\n"
    )
    assert result.cause == CAUSE_COMMAND_CONFIG


def test_unknown_cause_test_build():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: ninja: build stopped: subcommand failed\n"
    )
    assert result.cause == CAUSE_TEST_BUILD


def test_unknown_cause_package_tool():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: cargo failed to resolve package metadata\n"
    )
    assert result.cause == CAUSE_PACKAGE_TOOL


def test_unknown_cause_tool_action_specific():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: terraform failed while reading state backend\n"
    )
    assert result.cause == CAUSE_TOOL_ACTION_SPECIFIC


def test_unknown_cause_ambiguous_operational_fallback():
    result = decompose_unknown_cause(
        "2026-09-18T01:00:00Z Error: mysterious subsystem exploded\n"
    )
    assert result.cause == CAUSE_AMBIGUOUS_OPERATIONAL
    assert result.matched_evidence
