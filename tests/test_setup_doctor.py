from pathlib import Path

import pytest

from setup_doctor import (
    BLOCKED,
    PASS,
    WARN,
    _safe_workdir,
    build_recommended_yaml,
    detect_frameworks,
    inspect_setup,
    parse_requested_frameworks,
    required_permissions,
)


class FakeAPI:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        self.calls.append((method, path))
        if self.fail:
            raise RuntimeError("GitHub API GET failed with HTTP 403: forbidden")
        if path.endswith("/actions/runs?per_page=1"):
            return {"workflow_runs": []}
        return {"full_name": "o/r"}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def baseline_repo(tmp_path: Path) -> Path:
    write(
        tmp_path / "node/package.json",
        """{
          "private": true,
          "devDependencies": {
            "jest": "30.5.2",
            "jest-junit": "17.0.0",
            "vitest": "5.0.1"
          }
        }""",
    )
    write(
        tmp_path / "tests/test_example.py",
        "def test_example():\n    assert True\n",
    )
    write(
        tmp_path / ".github/workflows/ci.yml",
        """steps:
  - uses: actions/upload-artifact@v4
    with:
      name: junit-results-attempt-${{ github.run_attempt }}
      path: junit.xml
""",
    )
    return tmp_path


def status_map(report):
    return {item.name: item.status for item in report.checks}


def test_detects_pytest_jest_and_vitest(tmp_path):
    root = baseline_repo(tmp_path)

    assert detect_frameworks(root) == ("pytest", "jest", "vitest")
    assert parse_requested_frameworks("auto", detect_frameworks(root)) == (
        "pytest",
        "jest",
        "vitest",
    )


def test_ready_baseline_passes_with_read_only_api(tmp_path):
    root = baseline_repo(tmp_path)
    report = inspect_setup(
        root,
        requested_frameworks="pytest,jest,vitest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
        api=FakeAPI(),
        repo="o/r",
    )

    assert report.ready
    assert report.blocked == 0
    statuses = status_map(report)
    assert statuses["Framework detection"] == PASS
    assert statuses["Jest JUnit reporter"] == PASS
    assert statuses["JUnit artifact wiring"] == PASS
    assert statuses["GitHub API read access"] == PASS


def test_jest_without_junit_reporter_is_blocked(tmp_path):
    write(
        tmp_path / "package.json",
        '{"devDependencies":{"jest":"30.5.2"}}',
    )
    report = inspect_setup(
        tmp_path,
        requested_frameworks="jest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )

    assert not report.ready
    assert status_map(report)["Jest JUnit reporter"] == BLOCKED


def test_missing_artifact_prefix_is_warning_not_blocker(tmp_path):
    root = baseline_repo(tmp_path)
    report = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="different-prefix",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )

    assert report.ready
    assert status_map(report)["JUnit artifact wiring"] == WARN


def test_ownership_sources_are_validated(tmp_path):
    root = baseline_repo(tmp_path)
    write(tmp_path / ".github/CODEOWNERS", "/tests/** @qa-team\n")
    write(
        tmp_path / ".github/flaky-ownership.json",
        '{"version":1,"rules":[{"test_pattern":"pkg::*","owners":["@team"]}]}',
    )

    report = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=True,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )

    statuses = status_map(report)
    assert statuses["CODEOWNERS"] == PASS
    assert statuses["Flaky ownership map"] == PASS
    assert report.ready


def test_invalid_ownership_map_blocks_setup(tmp_path):
    root = baseline_repo(tmp_path)
    write(
        tmp_path / ".github/flaky-ownership.json",
        '{"version":2,"rules":[]}',
    )

    report = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=True,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )

    assert not report.ready
    assert status_map(report)["Flaky ownership map"] == BLOCKED


def test_quarantine_manifest_is_fail_closed(tmp_path):
    root = baseline_repo(tmp_path)

    missing = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=True,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )
    assert status_map(missing)["Quarantine manifest"] == BLOCKED

    write(
        root / ".github/flaky-quarantine.json",
        """{
          "version": 1,
          "entries": [{
            "test_id": "pkg::test",
            "approved_by": "human",
            "approved_at": "2026-09-19T00:00:00Z",
            "activated_run_id": 10,
            "expires_at": "2026-09-20T00:00:00Z",
            "reason": "doctor fixture"
          }]
        }""",
    )
    valid = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=True,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
    )
    assert status_map(valid)["Quarantine manifest"] == PASS


def test_write_permissions_are_recommended_but_not_probed(tmp_path):
    root = baseline_repo(tmp_path)

    permissions = required_permissions(
        rerun_mode="selective",
        triage_comment=True,
        issue_lifecycle=True,
    )
    assert permissions == (
        "contents: read",
        "actions: write",
        "pull-requests: write",
        "issues: write",
    )

    report = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=True,
        issue_lifecycle=True,
        rerun_mode="selective",
        api=FakeAPI(),
        repo="o/r",
    )
    assert report.ready
    assert status_map(report)["Required permissions"] == WARN


def test_api_read_failure_blocks_setup(tmp_path):
    root = baseline_repo(tmp_path)
    report = inspect_setup(
        root,
        requested_frameworks="pytest",
        junit_prefix="junit-results",
        ownership_routing=False,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=False,
        quarantine_manifest=".github/flaky-quarantine.json",
        quarantine_max_days=14,
        triage_comment=False,
        issue_lifecycle=False,
        rerun_mode="none",
        api=FakeAPI(fail=True),
        repo="o/r",
    )

    assert not report.ready
    assert status_map(report)["GitHub API read access"] == BLOCKED


def test_recommended_yaml_matches_requested_features():
    text = build_recommended_yaml(
        permissions=(
            "contents: read",
            "actions: write",
            "pull-requests: write",
            "issues: write",
        ),
        frameworks=("pytest",),
        junit_prefix="junit-results",
        ownership_routing=True,
        ownership_map=".github/flaky-ownership.json",
        quarantine_lifecycle=True,
        quarantine_manifest=".github/flaky-quarantine.json",
        triage_comment=True,
        issue_lifecycle=True,
        rerun_mode="selective",
    )

    assert "selective-rerun: 'true'" in text
    assert "flaky-test-intelligence: 'true'" in text
    assert "flaky-ownership-routing: 'true'" in text
    assert "quarantine-lifecycle: 'true'" in text
    assert "flaky-triage-comment: 'true'" in text
    assert "flaky-issue-lifecycle: 'true'" in text
    assert "actions: write" in text


def test_working_directory_cannot_escape_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    inside = workspace / "app"
    inside.mkdir()

    assert _safe_workdir(workspace, "app") == inside.resolve()

    with pytest.raises(ValueError):
        _safe_workdir(workspace, "../outside")
