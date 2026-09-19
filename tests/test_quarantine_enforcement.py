import json

import pytest

from quarantine_enforcement import (
    build_framework_command,
    evaluate_junit_enforcement,
    parse_active_tests,
)


def junit(*cases, failures=None, errors=None):
    body = "\n".join(cases)
    attrs = []
    if failures is not None:
        attrs.append(f'failures="{failures}"')
    if errors is not None:
        attrs.append(f'errors="{errors}"')
    attr_text = " ".join(attrs)
    return f"<testsuite {attr_text}>{body}</testsuite>"


def case(classname, name, status="pass"):
    marker = ""
    if status == "fail":
        marker = '<failure message="boom" />'
    if status == "error":
        marker = '<error message="crash" />'
    if status == "skip":
        marker = '<skipped />'
    return (
        f'<testcase classname="{classname}" name="{name}" time="1">'
        f"{marker}</testcase>"
    )


def test_parse_active_tests_rejects_duplicates_and_non_strings():
    assert parse_active_tests('["a::b","c::d"]') == ("a::b", "c::d")

    with pytest.raises(ValueError):
        parse_active_tests('["a::b","a::b"]')

    with pytest.raises(ValueError):
        parse_active_tests('["a::b",7]')


def test_pytest_adapter_injects_junit_path():
    command, env = build_framework_command(
        "pytest",
        ["python", "-m", "pytest", "-q"],
        "reports/pytest.xml",
    )

    assert "--junitxml=reports/pytest.xml" in command
    assert isinstance(env, dict)


def test_pytest_adapter_preserves_existing_junit_path():
    command, _ = build_framework_command(
        "pytest",
        ["pytest", "--junitxml=custom.xml"],
        "reports/pytest.xml",
    )

    assert command.count("--junitxml=custom.xml") == 1
    assert "--junitxml=reports/pytest.xml" not in command


def test_jest_adapter_adds_jest_junit_and_output_env():
    command, env = build_framework_command(
        "jest",
        ["npx", "jest", "--ci"],
        "reports/jest.xml",
    )

    assert "--reporters=jest-junit" in command
    assert env["JEST_JUNIT_OUTPUT_FILE"] == "reports/jest.xml"


def test_vitest_adapter_adds_builtin_junit_reporter():
    command, _ = build_framework_command(
        "vitest",
        ["npx", "vitest", "run"],
        "reports/vitest.xml",
    )

    assert "--reporter=junit" in command
    assert "--outputFile=reports/vitest.xml" in command


def test_only_active_quarantined_failures_are_allowed():
    xml = junit(
        case("pkg.TestCart", "test_total", "fail"),
        case("pkg.TestCart", "test_tax", "pass"),
        failures=1,
        errors=0,
    )

    result = evaluate_junit_enforcement(
        xml,
        framework="pytest",
        active_tests=("pkg.TestCart::test_total",),
        command_exit_code=1,
    )

    assert result.allowed_to_pass is True
    assert result.blocking_failures == ()
    assert result.quarantined_failures == ("pkg.TestCart::test_total",)


def test_non_quarantined_failure_keeps_ci_red():
    xml = junit(
        case("pkg.TestCart", "test_total", "fail"),
        case("pkg.TestCart", "test_tax", "fail"),
        failures=2,
        errors=0,
    )

    result = evaluate_junit_enforcement(
        xml,
        framework="jest",
        active_tests=("pkg.TestCart::test_total",),
        command_exit_code=1,
    )

    assert result.allowed_to_pass is False
    assert result.blocking_failures == ("pkg.TestCart::test_tax",)


def test_nonzero_command_without_failed_testcase_fails_closed():
    xml = junit(
        case("pkg.TestCart", "test_total", "pass"),
        failures=0,
        errors=0,
    )

    result = evaluate_junit_enforcement(
        xml,
        framework="vitest",
        active_tests=("pkg.TestCart::test_total",),
        command_exit_code=2,
    )

    assert result.allowed_to_pass is False
    assert "runner/configuration/collection" in result.reason


def test_unattributed_suite_failure_fails_closed():
    xml = junit(
        case("pkg.TestCart", "test_total", "pass"),
        failures=1,
        errors=0,
    )

    result = evaluate_junit_enforcement(
        xml,
        framework="pytest",
        active_tests=(),
        command_exit_code=1,
    )

    assert result.allowed_to_pass is False
    assert result.unattributed_failures == 1


def test_skipped_quarantined_test_does_not_count_as_failure():
    xml = junit(
        case("pkg.TestCart", "test_total", "skip"),
        failures=0,
        errors=0,
    )

    result = evaluate_junit_enforcement(
        xml,
        framework="pytest",
        active_tests=("pkg.TestCart::test_total",),
        command_exit_code=0,
    )

    assert result.allowed_to_pass is True
    assert result.failed_test_ids == ()
