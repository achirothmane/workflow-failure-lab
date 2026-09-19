from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ci_retry_gate import GitHubAPI
from flaky_ownership import load_ownership_map, parse_codeowners
from flaky_quarantine_lifecycle import load_manifest

PASS = "PASS"
WARN = "WARN"
BLOCKED = "BLOCKED"
SUPPORTED_FRAMEWORKS = ("pytest", "jest", "vitest")
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".tox",
    ".pytest_cache",
}
MAX_MANIFESTS = 200


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    fix: str = ""


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    detected_frameworks: tuple[str, ...]
    required_permissions: tuple[str, ...]

    @property
    def blocked(self) -> int:
        return sum(item.status == BLOCKED for item in self.checks)

    @property
    def warnings(self) -> int:
        return sum(item.status == WARN for item in self.checks)

    @property
    def ready(self) -> bool:
        return self.blocked == 0


def _bool(value: str, default: bool = False) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


def _safe_workdir(workspace: Path, value: str) -> Path:
    workspace = workspace.resolve()
    candidate = Path(value or ".")
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError("working-directory must stay inside GITHUB_WORKSPACE")
    if not candidate.is_dir():
        raise ValueError(f"working-directory does not exist: {candidate}")
    return candidate


def _iter_files(root: Path, names: set[str] | None = None):
    count = 0
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if names is not None and path.name not in names:
            continue
        yield path
        count += 1
        if count >= MAX_MANIFESTS:
            return


def _package_dependencies(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        value = data.get(key)
        if isinstance(value, dict):
            names.update(str(item).lower() for item in value)
    return names


def _pyproject_mentions_pytest(path: Path) -> bool:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False

    tool = data.get("tool")
    if isinstance(tool, dict) and isinstance(tool.get("pytest"), dict):
        return True

    project = data.get("project")
    if not isinstance(project, dict):
        return False

    values: list[str] = []
    deps = project.get("dependencies")
    if isinstance(deps, list):
        values.extend(str(item) for item in deps)
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                values.extend(str(item) for item in group)
    return any(re.match(r"\s*pytest(?:\b|[<>=!~])", item, re.I) for item in values)


def detect_frameworks(root: Path) -> tuple[str, ...]:
    found: set[str] = set()

    for package in _iter_files(root, {"package.json"}):
        deps = _package_dependencies(package)
        if "jest" in deps:
            found.add("jest")
        if "vitest" in deps:
            found.add("vitest")

    for config in (
        root / "pytest.ini",
        root / "tox.ini",
        root / "setup.cfg",
        root / "pyproject.toml",
    ):
        if not config.is_file():
            continue
        if config.name == "pyproject.toml" and _pyproject_mentions_pytest(config):
            found.add("pytest")
        elif "pytest" in config.read_text(encoding="utf-8", errors="ignore").lower():
            found.add("pytest")

    if "pytest" not in found:
        for path in _iter_files(root):
            if path.suffix != ".py":
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"(?m)^\s*def\s+test_", text):
                    found.add("pytest")
                    break

    return tuple(item for item in SUPPORTED_FRAMEWORKS if item in found)


def has_node_dependency(root: Path, dependency: str) -> bool:
    target = dependency.lower()
    for package in _iter_files(root, {"package.json"}):
        if target in _package_dependencies(package):
            return True
    return False


def parse_requested_frameworks(raw: str, detected: tuple[str, ...]) -> tuple[str, ...]:
    value = str(raw or "auto").strip().lower()
    if value == "auto":
        return detected
    parts = {
        item.strip().lower()
        for item in re.split(r"[,\s]+", value)
        if item.strip()
    }
    unknown = sorted(parts - set(SUPPORTED_FRAMEWORKS))
    if unknown:
        raise ValueError(f"unsupported frameworks: {', '.join(unknown)}")
    return tuple(item for item in SUPPORTED_FRAMEWORKS if item in parts)


def find_codeowners(root: Path) -> Path | None:
    for relative in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        path = root / relative
        if path.is_file():
            return path
    return None


def workflow_mentions_prefix(root: Path, prefix: str) -> bool:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return False
    for path in list(workflow_dir.glob("*.yml")) + list(workflow_dir.glob("*.yaml")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if prefix in text and "upload-artifact" in text:
            return True
    return False


def required_permissions(
    *,
    rerun_mode: str,
    triage_comment: bool,
    issue_lifecycle: bool,
) -> tuple[str, ...]:
    permissions = ["contents: read"]
    permissions.append("actions: write" if rerun_mode != "none" else "actions: read")
    if triage_comment:
        permissions.append("pull-requests: write")
    if issue_lifecycle:
        permissions.append("issues: write")
    return tuple(permissions)


def build_recommended_yaml(
    *,
    permissions: tuple[str, ...],
    frameworks: tuple[str, ...],
    junit_prefix: str,
    ownership_routing: bool,
    ownership_map: str,
    quarantine_lifecycle: bool,
    quarantine_manifest: str,
    triage_comment: bool,
    issue_lifecycle: bool,
    rerun_mode: str,
) -> str:
    lines = [
        "permissions:",
        *[f"  {item}" for item in permissions],
        "",
        "steps:",
        "  - uses: actions/checkout@v4",
        "  - uses: othy19904-eng/workflow-failure-lab@v1",
        "    with:",
        "      github-token: ${{ github.token }}",
        "      comment-on-pr: 'false'",
    ]
    if rerun_mode == "auto":
        lines.append("      auto-rerun: 'true'")
    elif rerun_mode == "selective":
        lines.append("      selective-rerun: 'true'")

    if frameworks:
        lines.extend(
            [
                "      flaky-test-intelligence: 'true'",
                f"      junit-artifact-prefix: '{junit_prefix}'",
            ]
        )
    if ownership_routing:
        lines.extend(
            [
                "      flaky-ownership-routing: 'true'",
                f"      flaky-ownership-map: '{ownership_map}'",
            ]
        )
    if quarantine_lifecycle:
        lines.extend(
            [
                "      quarantine-lifecycle: 'true'",
                f"      quarantine-manifest: '{quarantine_manifest}'",
            ]
        )
    if triage_comment:
        lines.append("      flaky-triage-comment: 'true'")
    if issue_lifecycle:
        lines.append("      flaky-issue-lifecycle: 'true'")
    return "\n".join(lines)


def inspect_setup(
    root: Path,
    *,
    requested_frameworks: str,
    junit_prefix: str,
    ownership_routing: bool,
    ownership_map: str,
    quarantine_lifecycle: bool,
    quarantine_manifest: str,
    quarantine_max_days: int,
    triage_comment: bool,
    issue_lifecycle: bool,
    rerun_mode: str,
    api: GitHubAPI | None = None,
    repo: str = "",
) -> DoctorReport:
    checks: list[DoctorCheck] = []
    detected = detect_frameworks(root)

    try:
        requested = parse_requested_frameworks(requested_frameworks, detected)
    except ValueError as exc:
        requested = ()
        checks.append(
            DoctorCheck(
                "Framework selection",
                BLOCKED,
                str(exc),
                "Use auto or a comma-separated subset of pytest,jest,vitest.",
            )
        )

    if requested:
        missing = [item for item in requested if item not in detected]
        if missing:
            checks.append(
                DoctorCheck(
                    "Framework detection",
                    BLOCKED,
                    f"Requested but not detected: {', '.join(missing)}.",
                    "Point working-directory at the project root or add the framework manifest/config.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "Framework detection",
                    PASS,
                    f"Detected: {', '.join(requested)}.",
                )
            )
    else:
        checks.append(
            DoctorCheck(
                "Framework detection",
                BLOCKED,
                "No supported pytest, Jest, or Vitest project was detected.",
                "Set frameworks explicitly or run the doctor from a supported project root.",
            )
        )

    if "jest" in requested:
        if has_node_dependency(root, "jest-junit"):
            checks.append(
                DoctorCheck(
                    "Jest JUnit reporter",
                    PASS,
                    "jest-junit is declared in a package manifest.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "Jest JUnit reporter",
                    BLOCKED,
                    "Jest is selected but jest-junit is not declared.",
                    "Install jest-junit as a devDependency; the Jest adapter uses it to emit JUnit.",
                )
            )

    if requested:
        if workflow_mentions_prefix(root, junit_prefix):
            checks.append(
                DoctorCheck(
                    "JUnit artifact wiring",
                    PASS,
                    f"A workflow uploads an artifact containing prefix {junit_prefix!r}.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "JUnit artifact wiring",
                    WARN,
                    f"No workflow upload-artifact step visibly uses prefix {junit_prefix!r}.",
                    "Upload JUnit XML with an artifact name that starts with this prefix; reruns should include attempt-N.",
                )
            )

    if ownership_routing:
        codeowners = find_codeowners(root)
        map_path = root / ownership_map
        valid_sources = 0

        if codeowners is not None:
            rules = parse_codeowners(codeowners.read_text(encoding="utf-8", errors="ignore"))
            if rules:
                valid_sources += 1
                checks.append(
                    DoctorCheck(
                        "CODEOWNERS",
                        PASS,
                        f"Loaded {len(rules)} rules from {codeowners.relative_to(root)}.",
                    )
                )
            else:
                checks.append(
                    DoctorCheck(
                        "CODEOWNERS",
                        WARN,
                        f"{codeowners.relative_to(root)} exists but no usable owner rules were parsed.",
                    )
                )

        if map_path.is_file():
            try:
                rules = load_ownership_map(map_path.read_text(encoding="utf-8"))
                valid_sources += 1
                checks.append(
                    DoctorCheck(
                        "Flaky ownership map",
                        PASS,
                        f"Loaded {len(rules)} explicit test-ID routing rules.",
                    )
                )
            except (ValueError, json.JSONDecodeError) as exc:
                checks.append(
                    DoctorCheck(
                        "Flaky ownership map",
                        BLOCKED,
                        f"Invalid {ownership_map}: {exc}",
                        "Fix the version-1 ownership map before enabling ownership routing.",
                    )
                )

        if valid_sources == 0:
            checks.append(
                DoctorCheck(
                    "Ownership routing source",
                    WARN,
                    "Ownership routing is enabled but neither CODEOWNERS nor a valid explicit map is available.",
                    "Add CODEOWNERS or a version-1 flaky ownership map; unresolved tests remain safe but unowned.",
                )
            )

    if quarantine_lifecycle:
        manifest = root / quarantine_manifest
        if not manifest.is_file():
            checks.append(
                DoctorCheck(
                    "Quarantine manifest",
                    BLOCKED,
                    f"{quarantine_manifest} does not exist.",
                    "Create a human-approved version-1 quarantine manifest before enabling lifecycle enforcement.",
                )
            )
        else:
            try:
                entries = load_manifest(
                    manifest.read_text(encoding="utf-8"),
                    max_days=quarantine_max_days,
                )
                checks.append(
                    DoctorCheck(
                        "Quarantine manifest",
                        PASS,
                        f"Validated {len(entries)} human-approved entries.",
                    )
                )
            except (ValueError, json.JSONDecodeError) as exc:
                checks.append(
                    DoctorCheck(
                        "Quarantine manifest",
                        BLOCKED,
                        f"Invalid {quarantine_manifest}: {exc}",
                        "Fix the manifest; quarantine lifecycle is fail-closed.",
                    )
                )

    if rerun_mode not in {"none", "auto", "selective"}:
        checks.append(
            DoctorCheck(
                "Rerun mode",
                BLOCKED,
                f"Unsupported rerun mode: {rerun_mode!r}.",
                "Use none, auto, or selective.",
            )
        )

    permissions = required_permissions(
        rerun_mode=rerun_mode if rerun_mode in {"none", "auto", "selective"} else "none",
        triage_comment=triage_comment,
        issue_lifecycle=issue_lifecycle,
    )
    checks.append(
        DoctorCheck(
            "Required permissions",
            WARN if (triage_comment or issue_lifecycle or rerun_mode != "none") else PASS,
            ", ".join(permissions),
            (
                "Write permissions are never probed by creating content. Configure them explicitly in the workflow."
                if (triage_comment or issue_lifecycle or rerun_mode != "none")
                else ""
            ),
        )
    )

    if api is not None and repo:
        try:
            api.request("GET", f"/repos/{repo}")
            api.request("GET", f"/repos/{repo}/actions/runs?per_page=1")
            checks.append(
                DoctorCheck(
                    "GitHub API read access",
                    PASS,
                    f"Repository and Actions history are readable for {repo}.",
                )
            )
        except RuntimeError as exc:
            checks.append(
                DoctorCheck(
                    "GitHub API read access",
                    BLOCKED,
                    str(exc),
                    "Grant contents: read and actions: read to the workflow token.",
                )
            )
    else:
        checks.append(
            DoctorCheck(
                "GitHub API read access",
                WARN,
                "Token or repository was not provided; API read access was not verified.",
            )
        )

    return DoctorReport(
        checks=tuple(checks),
        detected_frameworks=detected,
        required_permissions=permissions,
    )


def render_report(
    report: DoctorReport,
    *,
    recommended_yaml: str,
) -> str:
    verdict = "READY" if report.ready else "BLOCKED"
    lines = [
        "## CI Retry Gate Setup Doctor",
        "",
        f"**Verdict: {verdict}** · blocked **{report.blocked}** · warnings **{report.warnings}**",
        "",
        f"Detected frameworks: {', '.join(report.detected_frameworks) if report.detected_frameworks else 'none'}",
        "",
        "| Check | Status | Detail | Fix |",
        "|---|---|---|---|",
    ]
    for item in report.checks:
        detail = item.detail.replace("|", "/").replace("\n", " ")
        fix = item.fix.replace("|", "/").replace("\n", " ")
        lines.append(f"| {item.name} | **{item.status}** | {detail} | {fix} |")

    lines.extend(
        [
            "",
            "### Recommended production configuration",
            "",
            "~~~yaml",
            recommended_yaml,
            "~~~",
            "",
            "> The doctor is read-only. It validates configuration and read access but never tests write permissions by creating comments, Issues, reruns, or quarantines.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        print(f"{name}={value}")
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> int:
    workspace_raw = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()
    workspace = Path(workspace_raw)

    try:
        root = _safe_workdir(workspace, os.environ.get("INPUT_WORKING_DIRECTORY", "."))
        requested = os.environ.get("INPUT_FRAMEWORKS", "auto")
        junit_prefix = os.environ.get("INPUT_JUNIT_ARTIFACT_PREFIX", "junit-results").strip()
        if not junit_prefix:
            raise ValueError("junit-artifact-prefix must be non-empty")

        ownership_routing = _bool(os.environ.get("INPUT_FLAKY_OWNERSHIP_ROUTING", "false"))
        quarantine_lifecycle = _bool(os.environ.get("INPUT_QUARANTINE_LIFECYCLE", "false"))
        triage_comment = _bool(os.environ.get("INPUT_FLAKY_TRIAGE_COMMENT", "false"))
        issue_lifecycle = _bool(os.environ.get("INPUT_FLAKY_ISSUE_LIFECYCLE", "false"))
        fail_on_blocked = _bool(os.environ.get("INPUT_FAIL_ON_BLOCKED", "true"), True)
        quarantine_max_days = int(os.environ.get("INPUT_QUARANTINE_MAX_DAYS", "14"))
        rerun_mode = os.environ.get("INPUT_RERUN_MODE", "none").strip().lower()
        ownership_map = os.environ.get(
            "INPUT_FLAKY_OWNERSHIP_MAP",
            ".github/flaky-ownership.json",
        ).strip()
        quarantine_manifest = os.environ.get(
            "INPUT_QUARANTINE_MANIFEST",
            ".github/flaky-quarantine.json",
        ).strip()
    except (ValueError, TypeError) as exc:
        print(f"::error::Setup Doctor input error: {exc}")
        return 2

    token = os.environ.get("INPUT_GITHUB_TOKEN", "").strip()
    repo = (
        os.environ.get("INPUT_REPOSITORY", "").strip()
        or os.environ.get("GITHUB_REPOSITORY", "").strip()
    )
    api = GitHubAPI(
        token,
        os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    ) if token else None

    report = inspect_setup(
        root,
        requested_frameworks=requested,
        junit_prefix=junit_prefix,
        ownership_routing=ownership_routing,
        ownership_map=ownership_map,
        quarantine_lifecycle=quarantine_lifecycle,
        quarantine_manifest=quarantine_manifest,
        quarantine_max_days=quarantine_max_days,
        triage_comment=triage_comment,
        issue_lifecycle=issue_lifecycle,
        rerun_mode=rerun_mode,
        api=api,
        repo=repo,
    )
    try:
        requested_for_yaml = parse_requested_frameworks(requested, report.detected_frameworks)
    except ValueError:
        requested_for_yaml = report.detected_frameworks
    recommended = build_recommended_yaml(
        permissions=report.required_permissions,
        frameworks=requested_for_yaml,
        junit_prefix=junit_prefix,
        ownership_routing=ownership_routing,
        ownership_map=ownership_map,
        quarantine_lifecycle=quarantine_lifecycle,
        quarantine_manifest=quarantine_manifest,
        triage_comment=triage_comment,
        issue_lifecycle=issue_lifecycle,
        rerun_mode=rerun_mode,
    )
    markdown = render_report(report, recommended_yaml=recommended)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(markdown)
    else:
        print(markdown)

    _write_output("ready", "true" if report.ready else "false")
    _write_output("blocked-checks", str(report.blocked))
    _write_output("warnings", str(report.warnings))
    _write_output("detected-frameworks", ",".join(report.detected_frameworks))
    _write_output("required-permissions", ",".join(report.required_permissions))

    for check in report.checks:
        if check.status == BLOCKED:
            print(f"::error title=Setup Doctor: {check.name}::{check.detail}")
        elif check.status == WARN:
            print(f"::warning title=Setup Doctor: {check.name}::{check.detail}")

    if fail_on_blocked and not report.ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
