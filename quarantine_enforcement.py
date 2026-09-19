from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from flaky_test_intelligence import FAIL, observations_from_junit

SUPPORTED_FRAMEWORKS = {"pytest", "jest", "vitest"}


@dataclass(frozen=True)
class EnforcementResult:
    framework: str
    command_exit_code: int
    testcases_observed: int
    failed_test_ids: tuple[str, ...]
    quarantined_failures: tuple[str, ...]
    blocking_failures: tuple[str, ...]
    unattributed_failures: int
    allowed_to_pass: bool
    reason: str


def parse_active_tests(raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("active-tests-json must be valid JSON") from exc
    if not isinstance(value, list):
        raise ValueError("active-tests-json must be a JSON array")

    items: list[str] = []
    seen: set[str] = set()
    for raw_item in value:
        if not isinstance(raw_item, str) or not raw_item.strip():
            raise ValueError("every active quarantine test ID must be a non-empty string")
        item = raw_item.strip()
        if item in seen:
            raise ValueError(f"duplicate active quarantine test ID: {item}")
        seen.add(item)
        items.append(item)
    return tuple(items)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _int_attr(element: ET.Element, name: str) -> int:
    raw = str(element.attrib.get(name) or "0").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"JUnit {name} attribute must be an integer") from exc
    if value < 0:
        raise ValueError(f"JUnit {name} attribute must be non-negative")
    return value


def _leaf_suite_unattributed_failures(root: ET.Element) -> int:
    unattributed = 0
    suites = [element for element in root.iter() if _local_name(element.tag) == "testsuite"]
    for suite in suites:
        child_suites = [
            child for child in list(suite)
            if _local_name(child.tag) == "testsuite"
        ]
        if child_suites:
            continue

        declared = _int_attr(suite, "failures") + _int_attr(suite, "errors")
        testcase_failures = 0
        for case in suite.iter():
            if _local_name(case.tag) != "testcase":
                continue
            if any(
                _local_name(child.tag) in {"failure", "error"}
                for child in list(case)
            ):
                testcase_failures += 1

        direct_suite_failures = sum(
            _local_name(child.tag) in {"failure", "error"}
            for child in list(suite)
        )
        unattributed += direct_suite_failures
        if declared > testcase_failures + direct_suite_failures:
            unattributed += declared - testcase_failures - direct_suite_failures
    return unattributed


def evaluate_junit_enforcement(
    xml_text: str,
    *,
    framework: str,
    active_tests: tuple[str, ...],
    command_exit_code: int,
) -> EnforcementResult:
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ValueError(f"unsupported framework: {framework}")

    root = ET.fromstring(xml_text)
    observations = observations_from_junit(
        xml_text,
        sha="enforcement",
        run_id=1,
        attempt=1,
        job_name=framework,
    )
    failed = tuple(
        sorted({item.test_id for item in observations if item.status == FAIL})
    )
    active = set(active_tests)
    quarantined = tuple(item for item in failed if item in active)
    blocking = tuple(item for item in failed if item not in active)
    unattributed = _leaf_suite_unattributed_failures(root)

    if unattributed:
        return EnforcementResult(
            framework,
            command_exit_code,
            len(observations),
            failed,
            quarantined,
            blocking,
            unattributed,
            False,
            (
                f"JUnit reports {unattributed} failure/error(s) that cannot be "
                "attributed to a testcase; fail-closed."
            ),
        )

    if blocking:
        return EnforcementResult(
            framework,
            command_exit_code,
            len(observations),
            failed,
            quarantined,
            blocking,
            0,
            False,
            (
                f"{len(blocking)} non-quarantined test failure(s) remain; "
                "the CI gate must stay red."
            ),
        )

    if command_exit_code != 0 and not failed:
        return EnforcementResult(
            framework,
            command_exit_code,
            len(observations),
            failed,
            quarantined,
            blocking,
            0,
            False,
            (
                "The test command failed but JUnit contains no attributable failing "
                "testcase; treat this as runner/configuration/collection failure."
            ),
        )

    if command_exit_code != 0 and failed and len(quarantined) == len(failed):
        return EnforcementResult(
            framework,
            command_exit_code,
            len(observations),
            failed,
            quarantined,
            blocking,
            0,
            True,
            (
                f"All {len(failed)} failing testcase(s) are in the effective ACTIVE "
                "quarantine set. Failures remain visible but do not fail this gate."
            ),
        )

    return EnforcementResult(
        framework,
        command_exit_code,
        len(observations),
        failed,
        quarantined,
        blocking,
        0,
        True,
        "The test command and JUnit evidence contain no blocking failure.",
    )


def build_framework_command(
    framework: str,
    command: list[str],
    junit_path: str,
) -> tuple[list[str], dict[str, str]]:
    if framework not in SUPPORTED_FRAMEWORKS:
        raise ValueError(f"unsupported framework: {framework}")
    if not command:
        raise ValueError("test command must be non-empty")

    result = list(command)
    env = dict(os.environ)

    if framework == "pytest":
        if not any(
            arg == "--junitxml"
            or arg == "--junit-xml"
            or arg.startswith("--junitxml=")
            or arg.startswith("--junit-xml=")
            for arg in result
        ):
            result.append(f"--junitxml={junit_path}")

    elif framework == "jest":
        if not any("jest-junit" in arg for arg in result):
            result.extend(["--reporters=default", "--reporters=jest-junit"])
        env["JEST_JUNIT_OUTPUT_FILE"] = junit_path

    elif framework == "vitest":
        has_junit_reporter = any(
            arg in {"--reporter=junit", "--reporters=junit"}
            or "junit" in arg and arg.startswith("--reporter")
            for arg in result
        )
        if not has_junit_reporter:
            result.append("--reporter=junit")
        if not any(
            arg == "--outputFile"
            or arg.startswith("--outputFile=")
            for arg in result
        ):
            result.append(f"--outputFile={junit_path}")

    return result, env


def render_enforcement_report(result: EnforcementResult) -> str:
    lines = [
        "## Quarantine Enforcement",
        "",
        f"Framework: **{result.framework}**",
        f"Original command exit code: **{result.command_exit_code}**",
        f"JUnit testcases observed: **{result.testcases_observed}**",
        f"Quarantined failures: **{len(result.quarantined_failures)}**",
        f"Blocking failures: **{len(result.blocking_failures)}**",
        f"Unattributed failures/errors: **{result.unattributed_failures}**",
        "",
        f"**Decision:** {'PASS WITH QUARANTINE' if result.allowed_to_pass else 'FAIL'}",
        "",
        result.reason,
    ]
    if result.quarantined_failures:
        lines.extend(["", "Quarantined failures still observed:"])
        lines.extend(
            f"- `{item.replace(chr(96), chr(39))}`"
            for item in result.quarantined_failures
        )
    if result.blocking_failures:
        lines.extend(["", "Non-quarantined failures:"])
        lines.extend(
            f"- `{item.replace(chr(96), chr(39))}`"
            for item in result.blocking_failures
        )
    lines.extend(
        [
            "",
            "> Quarantined tests are still executed. This gate changes only whether "
            "their known ACTIVE failures fail the main CI path.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _append_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)


def _resolve_working_directory(value: str) -> Path:
    base = Path.cwd().resolve()
    candidate = Path(value or ".")
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()

    workspace_raw = os.environ.get("GITHUB_WORKSPACE")
    if workspace_raw:
        workspace = Path(workspace_raw).resolve()
        if not candidate.is_relative_to(workspace):
            raise ValueError("working-directory must stay inside GITHUB_WORKSPACE")

    if not candidate.is_dir():
        raise ValueError(f"working-directory does not exist or is not a directory: {candidate}")
    return candidate


def run_enforced(
    *,
    framework: str,
    active_tests_json: str,
    junit_path: str,
    command: list[str],
    working_directory: str = ".",
) -> int:
    active_tests = parse_active_tests(active_tests_json)
    workdir = _resolve_working_directory(working_directory)

    path = Path(junit_path)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    final_command, env = build_framework_command(
        framework,
        command,
        str(path),
    )
    completed = subprocess.run(
        final_command,
        env=env,
        cwd=workdir,
        check=False,
    )

    if not path.is_file():
        report = (
            "## Quarantine Enforcement\n\n"
            f"**Decision:** FAIL\n\nJUnit report `{path}` was not produced. "
            "The gate fails closed rather than masking an unknown command failure.\n"
        )
        _append_summary(report)
        _write_output("quarantine-gate-passed", "false")
        _write_output("blocking-failures", "unknown")
        return completed.returncode if completed.returncode != 0 else 2

    try:
        result = evaluate_junit_enforcement(
            path.read_text(encoding="utf-8"),
            framework=framework,
            active_tests=active_tests,
            command_exit_code=completed.returncode,
        )
    except (OSError, UnicodeDecodeError, ET.ParseError, ValueError) as exc:
        _append_summary(
            "## Quarantine Enforcement\n\n"
            f"**Decision:** FAIL\n\nJUnit validation failed: {exc}\n"
        )
        _write_output("quarantine-gate-passed", "false")
        _write_output("blocking-failures", "unknown")
        return completed.returncode if completed.returncode != 0 else 2

    _append_summary(render_enforcement_report(result))
    _write_output(
        "quarantine-gate-passed",
        "true" if result.allowed_to_pass else "false",
    )
    _write_output("blocking-failures", str(len(result.blocking_failures)))
    _write_output(
        "quarantined-failures",
        str(len(result.quarantined_failures)),
    )
    return 0 if result.allowed_to_pass else (
        completed.returncode if completed.returncode != 0 else 1
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run pytest, Jest, or Vitest while allowing only already-ACTIVE "
            "quarantined testcase failures to stop failing the main CI path."
        )
    )
    parser.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_FRAMEWORKS),
        required=True,
    )
    parser.add_argument("--active-tests-json", required=True)
    parser.add_argument("--junit-path", required=True)
    parser.add_argument(
        "--working-directory",
        default=".",
        help="Repository-relative directory in which to run the test command.",
    )
    parser.add_argument(
        "--command-string",
        default="",
        help="Test command parsed with shlex and executed without a shell.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Alternative test command after --",
    )
    args = parser.parse_args(argv)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if args.command_string and command:
        parser.error("use either --command-string or a command after --, not both")
    if args.command_string:
        command = shlex.split(args.command_string)
    if not command:
        parser.error("a test command is required")

    return run_enforced(
        framework=args.framework,
        active_tests_json=args.active_tests_json,
        junit_path=args.junit_path,
        command=command,
        working_directory=args.working_directory,
    )


if __name__ == "__main__":
    raise SystemExit(main())
