import io
import zipfile

from flaky_test_history import (
    _artifact_attempt,
    _xml_members,
    collect_flaky_history,
    render_flaky_history_report,
)
from flaky_test_intelligence import DO_NOT_QUARANTINE, QUARANTINE_CANDIDATE


def junit(status="pass", seconds=1.0):
    marker = "" if status == "pass" else '<failure message="boom" />'
    return f"""
    <testsuite>
      <testcase classname="pkg.TestCart" name="test_total" time="{seconds}">
        {marker}
      </testcase>
    </testsuite>
    """


def zip_xml(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class FakeAPI:
    def __init__(self, runs, artifacts, blobs):
        self.runs = runs
        self.artifacts = artifacts
        self.blobs = blobs

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        if "/actions/workflows/" in path and "/runs?" in path:
            return {"workflow_runs": self.runs}
        if "/actions/runs/" in path and "/artifacts?" in path:
            run_id = int(path.split("/actions/runs/", 1)[1].split("/", 1)[0])
            return {"artifacts": self.artifacts.get(run_id, [])}
        raise AssertionError(path)

    def request_bytes(self, method, path, accept="application/vnd.github+json"):
        artifact_id = int(path.split("/artifacts/", 1)[1].split("/", 1)[0])
        return self.blobs[artifact_id]


def test_attempt_provenance_is_fail_closed_for_reruns():
    assert _artifact_attempt("junit-results", 1) == 1
    assert _artifact_attempt("junit-results", 2) is None
    assert _artifact_attempt("junit-results-attempt-2", 2) == 2


def test_xml_members_reads_only_xml():
    blob = zip_xml({"report.xml": junit(), "notes.txt": "ignore"})
    members = _xml_members(blob)
    assert len(members) == 1
    assert members[0][0] == "report.xml"


def test_collects_same_sha_fail_pass_across_named_attempt_artifacts():
    runs = [
        {"id": 11, "head_sha": "sha-a", "run_attempt": 2, "workflow_id": 7},
        {"id": 12, "head_sha": "sha-b", "run_attempt": 2, "workflow_id": 7},
    ]
    artifacts = {
        11: [
            {"id": 101, "name": "junit-results-attempt-1", "expired": False},
            {"id": 102, "name": "junit-results-attempt-2", "expired": False},
        ],
        12: [
            {"id": 103, "name": "junit-results-attempt-1", "expired": False},
            {"id": 104, "name": "junit-results-attempt-2", "expired": False},
        ],
    }
    blobs = {
        101: zip_xml({"junit.xml": junit("fail", 20)}),
        102: zip_xml({"junit.xml": junit("pass", 18)}),
        103: zip_xml({"junit.xml": junit("fail", 22)}),
        104: zip_xml({"junit.xml": junit("pass", 19)}),
    }
    api = FakeAPI(runs, artifacts, blobs)

    result = collect_flaky_history(
        api,
        "o/r",
        runs[0],
        history_runs=20,
        artifact_prefix="junit-results",
    )

    assert result.artifacts_analyzed == 4
    assert result.observations == 4
    assert result.summaries[0].validated_recoveries == 2
    assert result.summaries[0].recommendation == QUARANTINE_CANDIDATE


def test_ambiguous_rerun_artifact_is_skipped():
    runs = [{"id": 11, "head_sha": "sha-a", "run_attempt": 2, "workflow_id": 7}]
    artifacts = {11: [{"id": 101, "name": "junit-results", "expired": False}]}
    api = FakeAPI(runs, artifacts, {101: zip_xml({"junit.xml": junit("fail")})})

    result = collect_flaky_history(
        api,
        "o/r",
        runs[0],
        history_runs=20,
        artifact_prefix="junit-results",
    )

    assert result.artifacts_skipped_ambiguous == 1
    assert result.artifacts_analyzed == 0
    assert result.observations == 0


def test_persistent_failure_blocks_quarantine():
    runs = [
        {"id": 11, "head_sha": "sha-a", "run_attempt": 2, "workflow_id": 7},
        {"id": 12, "head_sha": "sha-b", "run_attempt": 1, "workflow_id": 7},
    ]
    artifacts = {
        11: [
            {"id": 101, "name": "junit-results-attempt-1", "expired": False},
            {"id": 102, "name": "junit-results-attempt-2", "expired": False},
        ],
        12: [{"id": 103, "name": "junit-results", "expired": False}],
    }
    blobs = {
        101: zip_xml({"junit.xml": junit("fail", 10)}),
        102: zip_xml({"junit.xml": junit("pass", 9)}),
        103: zip_xml({"junit.xml": junit("fail", 11)}),
    }
    api = FakeAPI(runs, artifacts, blobs)

    result = collect_flaky_history(
        api,
        "o/r",
        runs[0],
        history_runs=20,
        artifact_prefix="junit-results",
    )

    assert result.summaries[0].persistent_failure_shas == 1
    assert result.summaries[0].recommendation == DO_NOT_QUARANTINE


def test_report_surfaces_counts_and_safety_note():
    runs = [{"id": 11, "head_sha": "sha-a", "run_attempt": 1, "workflow_id": 7}]
    artifacts = {11: [{"id": 101, "name": "junit-results", "expired": False}]}
    api = FakeAPI(runs, artifacts, {101: zip_xml({"junit.xml": junit("pass")})})

    result = collect_flaky_history(
        api,
        "o/r",
        runs[0],
        history_runs=20,
        artifact_prefix="junit-results",
    )
    report = render_flaky_history_report(result)

    assert "Flaky Test Intelligence" in report
    assert "JUnit artifacts analyzed: **1**" in report
    assert "Quarantine remains advisory only" in report
