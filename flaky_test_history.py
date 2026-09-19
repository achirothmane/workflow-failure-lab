from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone

from ci_retry_gate import GitHubAPI, _bool_env, _event_payload
from flaky_quarantine_lifecycle import (
    active_test_ids_json,
    evaluate_lifecycle,
    load_manifest_from_github,
    render_lifecycle_report,
)
from flaky_test_intelligence import (
    CaseObservation,
    FlakyTestSummary,
    observations_from_junit,
    summarize_flaky_tests,
)
from flaky_triage import (
    build_triage_items,
    emit_triage_annotations,
    render_triage_report,
    resolve_pr_number,
    upsert_pr_comment,
)

MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_XML_FILES_PER_ARTIFACT = 200
_ATTEMPT_RE = re.compile(r"(?:^|[-_.])attempt[-_.]?(\d+)(?:$|[-_.])", re.IGNORECASE)


@dataclass(frozen=True)
class FlakyHistoryResult:
    runs_scanned: int
    artifacts_seen: int
    artifacts_analyzed: int
    artifacts_skipped_ambiguous: int
    xml_files_analyzed: int
    observations: int
    summaries: tuple[FlakyTestSummary, ...]
    case_observations: tuple[CaseObservation, ...] = ()


def _artifact_attempt(name: str, run_attempt: int) -> int | None:
    match = _ATTEMPT_RE.search(name)
    if match:
        value = int(match.group(1))
        return value if value > 0 else None
    if run_attempt == 1:
        return 1
    return None


def _xml_members(blob: bytes) -> tuple[tuple[str, str], ...]:
    if len(blob) > MAX_ARTIFACT_BYTES:
        raise ValueError("artifact ZIP exceeds size limit")

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members = []
        total_uncompressed = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            if not info.filename.lower().endswith(".xml"):
                continue
            if len(members) >= MAX_XML_FILES_PER_ARTIFACT:
                raise ValueError("artifact contains too many XML files")
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > MAX_ARTIFACT_BYTES:
                raise ValueError("artifact XML payload exceeds size limit")
            raw = archive.read(info)
            members.append((info.filename, raw.decode("utf-8", errors="replace")))
        return tuple(members)


def _completed_runs(api: GitHubAPI, repo: str, current_run: dict, history_runs: int) -> list[dict]:
    workflow_id = current_run.get("workflow_id")
    if not workflow_id or history_runs <= 0:
        return []

    per_page = min(max(history_runs, 1), 100)
    data = api.request(
        "GET",
        f"/repos/{repo}/actions/workflows/{workflow_id}/runs?status=completed&per_page={per_page}",
    )
    runs = list(data.get("workflow_runs") or [])
    current_id = int(current_run.get("id") or 0)
    if current_id and all(int(item.get("id") or 0) != current_id for item in runs):
        runs.insert(0, current_run)
    return runs[:history_runs]


def collect_flaky_history(
    api: GitHubAPI,
    repo: str,
    current_run: dict,
    *,
    history_runs: int,
    artifact_prefix: str,
) -> FlakyHistoryResult:
    if history_runs < 1:
        return FlakyHistoryResult(0, 0, 0, 0, 0, 0, ())
    prefix = artifact_prefix.strip()
    if not prefix:
        raise ValueError("artifact_prefix must be non-empty")

    observations = []
    runs = _completed_runs(api, repo, current_run, history_runs)
    artifacts_seen = 0
    artifacts_analyzed = 0
    artifacts_skipped_ambiguous = 0
    xml_files_analyzed = 0

    for run in runs:
        run_id = int(run.get("id") or 0)
        sha = str(run.get("head_sha") or "").strip()
        run_attempt = max(1, int(run.get("run_attempt") or 1))
        if not run_id or not sha:
            continue

        data = api.request(
            "GET",
            f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100",
        )
        artifacts = [
            item
            for item in (data.get("artifacts") or [])
            if str(item.get("name") or "").startswith(prefix)
            and not bool(item.get("expired"))
        ]
        artifacts_seen += len(artifacts)

        for artifact in artifacts:
            artifact_id = int(artifact.get("id") or 0)
            name = str(artifact.get("name") or "")
            attempt = _artifact_attempt(name, run_attempt)
            if not artifact_id:
                continue
            if attempt is None:
                artifacts_skipped_ambiguous += 1
                continue

            blob = api.request_bytes(
                "GET",
                f"/repos/{repo}/actions/artifacts/{artifact_id}/zip",
                accept="application/vnd.github+json",
            )
            members = _xml_members(blob)
            if not members:
                continue

            artifacts_analyzed += 1
            for _, xml_text in members:
                xml_files_analyzed += 1
                observations.extend(
                    observations_from_junit(
                        xml_text,
                        sha=sha,
                        run_id=run_id,
                        attempt=attempt,
                        job_name=name or "junit",
                    )
                )

    summaries = summarize_flaky_tests(observations)
    return FlakyHistoryResult(
        runs_scanned=len(runs),
        artifacts_seen=artifacts_seen,
        artifacts_analyzed=artifacts_analyzed,
        artifacts_skipped_ambiguous=artifacts_skipped_ambiguous,
        xml_files_analyzed=xml_files_analyzed,
        observations=len(observations),
        summaries=summaries,
        case_observations=tuple(observations),
    )


def render_flaky_history_report(result: FlakyHistoryResult) -> str:
    candidates = [item for item in result.summaries if item.recommendation == "QUARANTINE_CANDIDATE"]
    waste_minutes = sum(item.estimated_waste_seconds for item in result.summaries) / 60.0
    lines = [
        "## Flaky Test Intelligence",
        "",
        f"Workflow runs scanned: **{result.runs_scanned}**",
        f"JUnit artifacts seen: **{result.artifacts_seen}**",
        f"JUnit artifacts analyzed: **{result.artifacts_analyzed}**",
        f"Ambiguous rerun artifacts skipped: **{result.artifacts_skipped_ambiguous}**",
        f"JUnit XML files analyzed: **{result.xml_files_analyzed}**",
        f"Test observations: **{result.observations}**",
        f"Tests ranked: **{len(result.summaries)}**",
        f"Human-reviewed quarantine candidates: **{len(candidates)}**",
        f"Estimated test-level CI waste: **{waste_minutes:.2f} min**",
        "",
    ]

    if result.summaries:
        lines.extend(
            [
                "| Test | Failures | Same-SHA recoveries | Persistent failure SHAs | Waste | Recommendation |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for item in result.summaries[:20]:
            test_id = item.test_id.replace("|", "/").replace("`", "'")
            lines.append(
                f"| `{test_id}` | {item.failures} | {item.validated_recoveries} | "
                f"{item.persistent_failure_shas} | {item.estimated_waste_minutes:.2f} min | "
                f"`{item.recommendation}` |"
            )
    else:
        lines.append(
            "No analyzable test observations were found. Ensure the source workflow uploads "
            "JUnit XML artifacts with the configured prefix."
        )

    lines.extend(
        [
            "",
            "> Quarantine remains advisory only. A newer-SHA pass never proves that an older-SHA failure was flaky.",
            "> For rerun workflows (`run_attempt > 1`), artifact names must include `attempt-N` "
            "(for example `junit-results-attempt-2`). Ambiguous rerun artifacts are skipped.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    event = _event_payload()
    workflow_run = event.get("workflow_run") or {}
    run_id_raw = (
        os.environ.get("INPUT_RUN_ID")
        or workflow_run.get("id")
        or os.environ.get("GITHUB_RUN_ID")
    )
    history_runs = min(max(int(os.environ.get("INPUT_FLAKY_HISTORY_RUNS", "20")), 1), 50)
    artifact_prefix = os.environ.get("INPUT_JUNIT_ARTIFACT_PREFIX", "junit-results")
    quarantine_lifecycle = _bool_env("INPUT_QUARANTINE_LIFECYCLE", False)
    triage_comment = _bool_env("INPUT_FLAKY_TRIAGE_COMMENT", False)
    quarantine_manifest = os.environ.get(
        "INPUT_QUARANTINE_MANIFEST",
        ".github/flaky-quarantine.json",
    )
    quarantine_max_days = int(
        os.environ.get("INPUT_QUARANTINE_MAX_DAYS", "14")
    )
    release_clean_shas = int(
        os.environ.get("INPUT_QUARANTINE_RELEASE_CLEAN_SHAS", "3")
    )

    if not token or not repo:
        print("::error::github-token and repository are required")
        return 2
    try:
        run_id = int(run_id_raw)
    except (TypeError, ValueError):
        print("::error::run-id could not be determined")
        return 2

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    current_run = api.get_run(repo, run_id)

    try:
        result = collect_flaky_history(
            api,
            repo,
            current_run,
            history_runs=history_runs,
            artifact_prefix=artifact_prefix,
        )
    except (RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"::warning::Flaky Test Intelligence could not analyze artifacts: {exc}")
        return 0

    report = render_flaky_history_report(result)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)

    candidates = sum(item.recommendation == "QUARANTINE_CANDIDATE" for item in result.summaries)
    waste_minutes = sum(item.estimated_waste_seconds for item in result.summaries) / 60.0

    active_count = 0
    expired_count = 0
    released_count = 0
    blocked_count = 0
    active_json = "[]"
    lifecycle = None

    if quarantine_lifecycle:
        try:
            entries = load_manifest_from_github(
                api,
                repo,
                str(current_run.get("head_sha") or ""),
                quarantine_manifest,
                max_days=quarantine_max_days,
            )
            if entries is None:
                lifecycle_report = (
                    "## Flaky Quarantine Lifecycle\n\n"
                    f"No quarantine manifest was found at `{quarantine_manifest}` "
                    "on the target revision. No test is quarantined.\n"
                )
            else:
                lifecycle = evaluate_lifecycle(
                    entries,
                    result.summaries,
                    result.case_observations,
                    now=datetime.now(timezone.utc),
                    release_clean_shas=release_clean_shas,
                )
                lifecycle_report = render_lifecycle_report(
                    lifecycle,
                    manifest_path=quarantine_manifest,
                )
                active_count = len(lifecycle.active)
                expired_count = len(lifecycle.expired)
                released_count = len(lifecycle.released)
                blocked_count = len(lifecycle.blocked)
                active_json = active_test_ids_json(lifecycle)

            if summary_path:
                with open(summary_path, "a", encoding="utf-8") as handle:
                    handle.write(lifecycle_report)
            else:
                print(lifecycle_report)
        except (RuntimeError, ValueError) as exc:
            print(
                "::warning::Quarantine Lifecycle failed closed; "
                f"no quarantine is active: {exc}"
            )

    triage_items = build_triage_items(result.summaries, lifecycle)
    triage_report = render_triage_report(
        triage_items,
        repo=repo,
        run_id=run_id,
    )
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(triage_report)
    else:
        print(triage_report)

    annotations_emitted = emit_triage_annotations(triage_items)
    triage_comment_posted = False
    if triage_comment and triage_items:
        pr_number = resolve_pr_number(event, current_run)
        if pr_number is None:
            print(
                "::warning::Flaky triage PR comment requested, but no pull request "
                "could be associated with the analyzed workflow run."
            )
        else:
            try:
                action = upsert_pr_comment(
                    api,
                    repo,
                    pr_number,
                    triage_report,
                )
                triage_comment_posted = True
                print(
                    f"::notice::Flaky triage PR comment {action} on PR #{pr_number}."
                )
            except (RuntimeError, ValueError) as exc:
                print(
                    "::warning::Could not publish flaky triage PR comment: "
                    f"{exc}"
                )

    _write_output("flaky-tests-observed", str(len(result.summaries)))
    _write_output("quarantine-candidates", str(candidates))
    _write_output("junit-artifacts-analyzed", str(result.artifacts_analyzed))
    _write_output("flaky-estimated-waste-minutes", f"{waste_minutes:.2f}")
    _write_output("active-quarantines", str(active_count))
    _write_output("expired-quarantines", str(expired_count))
    _write_output("auto-released-quarantines", str(released_count))
    _write_output("blocked-quarantines", str(blocked_count))
    _write_output("active-quarantine-tests-json", active_json)
    _write_output("flaky-triage-items", str(len(triage_items)))
    _write_output("flaky-triage-annotations", str(annotations_emitted))
    _write_output(
        "flaky-triage-comment-posted",
        "true" if triage_comment_posted else "false",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
