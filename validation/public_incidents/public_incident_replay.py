from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

from ci_retry_gate import assess_authenticated_runner_annotations, assess_job
from evidence_gate import build_ci_retry_decision
from evidence_producer import produce_ci_evidence_bundle
from validation.public_incidents.public_incident_corpus import (
    PUBLIC_INCIDENT_CORPUS_V3,
    PUBLIC_INCIDENT_CORPUS_V4,
    PUBLIC_INCIDENT_CORPUS_V5,
    PublicIncident,
)


EXPECTED_ALLOW = "ALLOW"
EXPECTED_BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class PublicIncidentReplayFixture:
    case_id: str
    log_excerpt: str
    job_name: str
    failed_step_name: str
    expected_decision: str
    fixture_basis: str
    source_job: dict | None = None
    head_sha: str = ""
    check_run: dict | None = None
    check_annotations: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class PublicIncidentReplayResult:
    case_id: str
    repository: str
    expected_decision: str
    actual_decision: str
    evidence_status: str
    category: str
    confidence: str
    provenance_status: str
    reason: str

    @property
    def false_allow(self) -> bool:
        return (
            self.expected_decision == EXPECTED_BLOCK
            and self.actual_decision == EXPECTED_ALLOW
        )

    @property
    def false_block(self) -> bool:
        return (
            self.expected_decision == EXPECTED_ALLOW
            and self.actual_decision == EXPECTED_BLOCK
        )


@dataclass(frozen=True, slots=True)
class PublicIncidentReplaySummary:
    results: tuple[PublicIncidentReplayResult, ...]
    missing_case_ids: tuple[str, ...]
    corpus_size: int

    @property
    def replayed_cases(self) -> int:
        return len({result.case_id for result in self.results})

    @property
    def coverage(self) -> float:
        if self.corpus_size <= 0:
            return 1.0
        return self.replayed_cases / self.corpus_size

    @property
    def false_allows(self) -> int:
        return sum(result.false_allow for result in self.results)

    @property
    def false_blocks(self) -> int:
        return sum(result.false_block for result in self.results)

    @property
    def unknown_evidence(self) -> int:
        return sum(
            result.evidence_status == "UNKNOWN"
            for result in self.results
        )

    @property
    def gate_passed(self) -> bool:
        return (
            not self.missing_case_ids
            and self.false_allows == 0
            and self.false_blocks == 0
        )


PUBLIC_INCIDENT_REPLAY_FIXTURES_V1 = (
    PublicIncidentReplayFixture(
        case_id="geophires-x-526-runner-shutdown",
        log_excerpt=(
            "2026-09-25T15:09:11.8683548Z ##[group]Run tox -e py39 -v\n"
            "2026-09-25T15:46:07.1326164Z "
            "tests/test_pre_commit_config.py::PreCommitConfigTestCase::"
            "test_pre_commit_exclude_pattern PASSED [100%]\n"
            "2026-09-25T15:46:07.2362061Z ##[error]"
            "The runner has received a shutdown signal. This can happen when "
            "the runner service is stopped, or a manually started runner is canceled.\n"
            "2026-09-25T15:46:07.2364052Z ##[error]"
            "Process completed with exit code 143.\n"
        ),
        job_name="py39 (ubuntu)",
        failed_step_name="test",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "Reduced from the reproduced GEOPHIRES-X #526 py39 failure log."
        ),
    ),
    PublicIncidentReplayFixture(
        case_id="deck-streak-439-runaway-mutant",
        log_excerpt=(
            "err=interrupted phase=Test\n"
            "##[error]The runner has received a shutdown signal.\n"
            "##[error]Process completed with exit code 143.\n"
        ),
        job_name="mutation-rust",
        failed_step_name="cargo mutants",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "Reduced from the terminal symptom described in deck-streak #439; "
            "the issue later ties repeated losses to a runaway allocating mutant."
        ),
    ),
    PublicIncidentReplayFixture(
        case_id="1-bit-bridge-1098-fuzz-oom",
        log_excerpt=(
            "##[error]The runner has received a shutdown signal.\n"
            "##[error]Process completed with exit code 143.\n"
        ),
        job_name="FuzzExtractFLAC",
        failed_step_name="Fuzz",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "Reduced from the repeated nightly symptom documented by "
            "1-bit-bridge PR #1098; later reproduction identified input-driven OOM."
        ),
    ),
)


PUBLIC_INCIDENT_REPLAY_FIXTURES_V2 = PUBLIC_INCIDENT_REPLAY_FIXTURES_V1 + (
    PublicIncidentReplayFixture(
        case_id="alunduil-chezmoi-curl-reset-2026-07-27",
        log_excerpt=(
            "2026-07-27T05:48:24.4625815Z curl: (35) Recv failure: Connection reset by peer\n"
            "2026-07-27T05:48:24.4664017Z ##[error]Process completed with exit code 35.\n"
        ),
        job_name="Run pre-commit hooks",
        failed_step_name="Install lychee",
        expected_decision=EXPECTED_ALLOW,
        fixture_basis=(
            "GitHub run 30240791215 attempt 1 failed during the lychee download; "
            "attempt 2 reran the same job successfully on the same workflow run."
        ),
        source_job={
            "id": 89897364311,
            "name": "Run pre-commit hooks",
            "conclusion": "failure",
            "started_at": "2026-07-27T05:48:19Z",
            "completed_at": "2026-07-27T05:48:26Z",
            "steps": [
                {"name": "Set up job", "conclusion": "success"},
                {"name": "Run actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", "conclusion": "success"},
                {"name": "Run actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1", "conclusion": "success"},
                {
                    "name": "Install lychee",
                    "conclusion": "failure",
                    "started_at": "2026-07-27T05:48:24Z",
                    "completed_at": "2026-07-27T05:48:24Z",
                },
                {"name": "Run pre-commit/action@2c7b3805fd2a0fd8c1884dcaebf91fc102a13ecd", "conclusion": "skipped"},
                {"name": "Post Run actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1", "conclusion": "skipped"},
                {"name": "Post Run actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803", "conclusion": "success"},
                {"name": "Complete job", "conclusion": "success"},
            ],
        },
        head_sha="b39e831f09dc65b59d7c81a1b55daa54ddb2af37",
    ),
    PublicIncidentReplayFixture(
        case_id="uzi-curl-reset-2026-09-05",
        log_excerpt=(
            "2026-09-05T18:48:22.9603575Z [lint:controller] curl: (35) "
            "Recv failure: Connection reset by peer\n"
            "2026-09-05T18:48:22.9640664Z ##[error]exit status 2\n"
            "2026-09-05T18:48:22.9659229Z ##[error]Process completed with exit code 201.\n"
        ),
        job_name="lint-controller",
        failed_step_name="lint + deadcode + vulncheck",
        expected_decision=EXPECTED_ALLOW,
        fixture_basis=(
            "GitHub run 33985176395 attempt 1 failed on a curl connection reset; "
            "attempt 2 reran the same job successfully on the same SHA."
        ),
        source_job={
            "id": 101357253123,
            "name": "lint-controller",
            "conclusion": "failure",
            "started_at": "2026-09-05T18:48:04Z",
            "completed_at": "2026-09-05T18:48:25Z",
            "steps": [
                {"name": "Set up job", "conclusion": "success"},
                {"name": "Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "conclusion": "success"},
                {"name": "Run actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e", "conclusion": "success"},
                {"name": "Run ./.github/actions/setup-task", "conclusion": "success"},
                {"name": "go mod download", "conclusion": "success"},
                {"name": "Fetch origin/main for the ratchet", "conclusion": "success"},
                {
                    "name": "lint + deadcode + vulncheck",
                    "conclusion": "failure",
                    "started_at": "2026-09-05T18:48:22Z",
                    "completed_at": "2026-09-05T18:48:22Z",
                },
                {"name": "Post Run actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e", "conclusion": "skipped"},
                {"name": "Post Run actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", "conclusion": "success"},
                {"name": "Complete job", "conclusion": "success"},
            ],
        },
        head_sha="65a181eef66cfa27e611c2504b78beae0c8d4efe",
    ),
    PublicIncidentReplayFixture(
        case_id="docker-compose-registry-502-2026-09-16",
        log_excerpt=(
            "2026-09-16T22:05:31.0016382Z #7 ERROR: unexpected status from HEAD request "
            "to https://registry-1.docker.io/v2/docker/buildkit-syft-scanner/manifests/1.11.0: "
            "502 Bad Gateway\n"
            "2026-09-16T22:05:31.3692870Z ERROR: failed to solve: unexpected status from "
            "HEAD request to https://registry-1.docker.io/v2/docker/buildkit-syft-scanner/"
            "manifests/1.11.0: 502 Bad Gateway\n"
            "2026-09-16T22:05:31.4659302Z ##[error]buildx bake failed with: ERROR: "
            "failed to solve: unexpected status from HEAD request to "
            "https://registry-1.docker.io/v2/docker/buildkit-syft-scanner/manifests/1.11.0: "
            "502 Bad Gateway\n"
        ),
        job_name="relay-image-test / build (0, linux/amd64, ubuntu-24.04)",
        failed_step_name="Build",
        expected_decision=EXPECTED_ALLOW,
        fixture_basis=(
            "GitHub run 35155815118 attempt 1 failed on repeated Docker Hub 502 responses; "
            "attempt 2 reran the same build job successfully."
        ),
        source_job={
            "id": 104994979798,
            "name": "relay-image-test / build (0, linux/amd64, ubuntu-24.04)",
            "conclusion": "failure",
            "started_at": "2026-09-16T22:05:09Z",
            "completed_at": "2026-09-16T22:05:34Z",
            "steps": [
                {"name": "Set up job", "conclusion": "success"},
                {"name": "Require GitHub-hosted Linux runner", "conclusion": "success"},
                {"name": "Install dependencies", "conclusion": "success"},
                {"name": "Docker meta", "conclusion": "success"},
                {"name": "Set up QEMU", "conclusion": "skipped"},
                {"name": "Set GitHub runtime outputs", "conclusion": "success"},
                {"name": "Set up Docker Buildx", "conclusion": "success"},
                {"name": "Install Cosign", "conclusion": "success"},
                {"name": "Prepare", "conclusion": "success"},
                {"name": "Configure AWS credentials", "conclusion": "skipped"},
                {"name": "Login to Amazon ECR", "conclusion": "skipped"},
                {"name": "Authenticate to Google Cloud", "conclusion": "skipped"},
                {"name": "Login to Google Artifact Registry", "conclusion": "skipped"},
                {"name": "Login to Docker Hub with OIDC", "conclusion": "skipped"},
                {"name": "Login to registry", "conclusion": "skipped"},
                {
                    "name": "Build",
                    "conclusion": "failure",
                    "started_at": "2026-09-16T22:05:28Z",
                    "completed_at": "2026-09-16T22:05:31Z",
                },
                {"name": "Get image digest", "conclusion": "skipped"},
                {"name": "Login to registry for signing", "conclusion": "skipped"},
                {"name": "Signing attestation manifests", "conclusion": "skipped"},
                {"name": "Signing local artifacts", "conclusion": "skipped"},
                {"name": "List local output", "conclusion": "skipped"},
                {"name": "Upload artifact", "conclusion": "skipped"},
                {"name": "Set result output", "conclusion": "skipped"},
                {"name": "Post Build", "conclusion": "success"},
                {"name": "Post Set up Docker Buildx", "conclusion": "success"},
                {"name": "Complete job", "conclusion": "success"},
            ],
        },
        head_sha="ab98eda5d81444d0e64ae6eddb1ebf43a26c3e06",
    ),
)


PUBLIC_INCIDENT_REPLAY_FIXTURES_V3 = PUBLIC_INCIDENT_REPLAY_FIXTURES_V2 + (
    PublicIncidentReplayFixture(
        case_id="alethialabs-helm-network-unreachable-2026-08-26",
        log_excerpt=(
            "2026-08-26T06:28:35.9287308Z       Error: looks like "
            "\"https://grafana.github.io/helm-charts\" is not a valid chart repository "
            "or cannot be reached: Get \"https://grafana.github.io/helm-charts/index.yaml\": "
            "dial tcp [2606:50c0:8001::153]:443: connect: network is unreachable\n"
            "2026-08-26T06:28:35.9355157Z ##[error]Process completed with exit code 1.\n"
        ),
        job_name="Add-on charts render (helm template · pinned charts)",
        failed_step_name="Every add-on renders with its pinned chart and its own defaults",
        expected_decision=EXPECTED_ALLOW,
        fixture_basis=(
            "GitHub run 32938269387 attempt 1 failed on an IPv6 network-unreachable "
            "dependency fetch; attempt 2 reran the same job successfully."
        ),
        source_job={
            "id": 98083760153,
            "name": "Add-on charts render (helm template · pinned charts)",
            "conclusion": "failure",
            "started_at": "2026-08-26T06:28:01Z",
            "completed_at": "2026-08-26T06:28:38Z",
            "steps": [
                {
                    "name": "Every add-on renders with its pinned chart and its own defaults",
                    "conclusion": "failure",
                    "started_at": "2026-08-26T06:28:08Z",
                    "completed_at": "2026-08-26T06:28:35Z",
                }
            ],
        },
        head_sha="449485655f06168e8968e812a71db20e913d0859",
    ),
    PublicIncidentReplayFixture(
        case_id="prql-hosted-runner-loss-2026-08-26",
        log_excerpt=(
            "The hosted runner lost communication with the server. Anything in your "
            "workflow that terminates the runner process, starves it for CPU/Memory, "
            "or blocks its network access can cause this error.\n"
        ),
        job_name="nightly / nightly-release / build-prqlc-c (macos-15, aarch64-apple-darwin)",
        failed_step_name="",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "PRQL #6236 records the GitHub hosted-runner-loss annotation and a successful "
            "attempt-2 rerun, but the failed job uploaded no log blob and exposes no failed "
            "step metadata. V3 intentionally preserves fail-closed authority."
        ),
        source_job={
            "id": 98152972844,
            "name": "nightly / nightly-release / build-prqlc-c (macos-15, aarch64-apple-darwin)",
            "conclusion": "failure",
            "started_at": "2026-08-26T11:07:03Z",
            "completed_at": "2026-08-26T11:55:03Z",
            "steps": [],
        },
        head_sha="d63e9573daa23943ab666d26a4fe34da8f4deae6",
    ),
    PublicIncidentReplayFixture(
        case_id="hiromi-github-rate-limit-recurrence-2026-09-26",
        log_excerpt=(
            "2026-09-26T14:25:15.9912973Z ##[error]Unable to process file command "
            "'output' successfully.\n"
            "2026-09-26T14:25:15.9921300Z ##[error]Invalid format "
            "'\\t\"message\": \"API rate limit exceeded for user ID 6440811.\"'\n"
        ),
        job_name="test",
        failed_step_name="Find associated pull request",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "GitHub run 36248287482 attempt 1 failed after the test suite passed; attempt 2 "
            "failed again in the same job and same step with the same API-rate-limit shape."
        ),
        source_job={
            "id": 108421448279,
            "name": "test",
            "conclusion": "failure",
            "started_at": "2026-09-26T14:22:32Z",
            "completed_at": "2026-09-26T14:25:19Z",
            "steps": [
                {
                    "name": "Find associated pull request",
                    "conclusion": "failure",
                    "started_at": "2026-09-26T14:25:15Z",
                    "completed_at": "2026-09-26T14:25:15Z",
                }
            ],
        },
        head_sha="ca2b96f441fc0aeb1514557d5cefa9ccbe4b1efc",
    ),
)


_PRQL_V3_FIXTURE = next(
    fixture
    for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V3
    if fixture.case_id == "prql-hosted-runner-loss-2026-08-26"
)

_PRQL_V4_FIXTURE = replace(
    _PRQL_V3_FIXTURE,
    expected_decision=EXPECTED_BLOCK,
    fixture_basis=(
        "PRQL #6236 records the hosted-runner-loss annotation and successful attempt-2 "
        "rerun. V4 replays the annotation through an exact GitHub Actions check-run "
        "binding rather than injecting retrospective issue text into the ordinary log path. "
        "The job remains BLOCK because its release-shaped identity crosses the existing "
        "side-effect boundary."
    ),
    source_job={
        **(_PRQL_V3_FIXTURE.source_job or {}),
        "head_sha": "d63e9573daa23943ab666d26a4fe34da8f4deae6",
        "check_run_url": (
            "https://api.github.com/repos/PRQL/prql/check-runs/98152972844"
        ),
    },
    check_run={
        "id": 98152972844,
        "name": (
            "nightly / nightly-release / build-prqlc-c "
            "(macos-15, aarch64-apple-darwin)"
        ),
        "status": "completed",
        "conclusion": "failure",
        "head_sha": "d63e9573daa23943ab666d26a4fe34da8f4deae6",
        "app": {"slug": "github-actions"},
    },
    check_annotations=(
        {
            "annotation_level": "failure",
            "message": (
                "The hosted runner lost communication with the server. Anything in your "
                "workflow that terminates the runner process, starves it for CPU/Memory, "
                "or blocks its network access can cause this error."
            ),
        },
    ),
)

PUBLIC_INCIDENT_REPLAY_FIXTURES_V4 = tuple(
    _PRQL_V4_FIXTURE
    if fixture.case_id == _PRQL_V4_FIXTURE.case_id
    else fixture
    for fixture in PUBLIC_INCIDENT_REPLAY_FIXTURES_V3
)


PUBLIC_INCIDENT_REPLAY_FIXTURES_V5 = PUBLIC_INCIDENT_REPLAY_FIXTURES_V4 + (
    PublicIncidentReplayFixture(
        case_id="runner-images-13719-prestep-disk-exhaustion",
        log_excerpt=(
            "System.IO.IOException: No space left on device : "
            "'/home/runner/actions-runner/cached/_diag/Worker_20260223-165456-utc.log'\n"
        ),
        job_name="hosted-runner initialization",
        failed_step_name="",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "actions/runner-images #13719 reports the worker failing before any workflow "
            "step, on a tiny repository with no build/cache workload; multiple reruns and "
            "switching ubuntu-latest to ubuntu-22.04 reproduced the same pre-step failure. "
            "The replay job shell is deterministic scaffolding only, not claimed upstream metadata."
        ),
    ),
    PublicIncidentReplayFixture(
        case_id="serverless-cfn-lint-dns-retry-exhaustion-2025-11-19",
        log_excerpt=(
            "socket.gaierror: [Errno -3] Temporary failure in name resolution\n"
            "urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>\n"
            "cfn-lint schema update failed, retrying... (attempt 1 of 3)\n"
            "urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>\n"
            "cfn-lint schema update failed, retrying... (attempt 2 of 3)\n"
            "urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>\n"
            "cfn-lint schema update failed after 3 attempts\n"
            "make: *** [Makefile:57: lint] Error 1\n"
        ),
        job_name="ubuntu-latest / 3.9",
        failed_step_name="",
        expected_decision=EXPECTED_BLOCK,
        fixture_basis=(
            "aws-cloudformation/cfn-lint #4296 preserves the full failure text for "
            "serverless-application-model run 19517345578 / failed job 55875798766. "
            "GitHub's latest-attempt job list shows the same ubuntu-latest / 3.9 identity "
            "later succeeded as job 55876077959. The issue-preserved log lacks GitHub "
            "runner timestamps and failed-step timing metadata, so that retrospective "
            "recovery must not be relabeled as decision-time provenance."
        ),
        source_job={
            "id": 55875798766,
            "name": "ubuntu-latest / 3.9",
            "conclusion": "failure",
            "steps": [],
        },
    ),
)


def _incident_index() -> dict[str, PublicIncident]:
    return {incident.case_id: incident for incident in PUBLIC_INCIDENT_CORPUS_V5}


def _replay_job(fixture: PublicIncidentReplayFixture, ordinal: int) -> dict:
    if fixture.source_job is not None:
        return fixture.source_job

    # The job shell is deterministic replay scaffolding, not claimed upstream
    # metadata. Source-backed information is kept in the fixture log/basis.
    start_minute = 10 + ordinal
    end_minute = start_minute + 5
    return {
        "id": 90_000 + ordinal,
        "name": fixture.job_name,
        "conclusion": "failure",
        "started_at": f"2026-09-25T15:{start_minute:02d}:00Z",
        "completed_at": f"2026-09-25T15:{end_minute:02d}:00Z",
        "steps": [
            {
                "name": fixture.failed_step_name,
                "conclusion": "failure",
                "started_at": f"2026-09-25T15:{start_minute:02d}:00Z",
                "completed_at": f"2026-09-25T15:{end_minute:02d}:00Z",
            }
        ],
    }


def replay_public_incident(
    fixture: PublicIncidentReplayFixture,
    *,
    ordinal: int,
) -> PublicIncidentReplayResult:
    incidents = _incident_index()
    incident = incidents.get(fixture.case_id)
    if incident is None:
        raise ValueError(f"Replay fixture references unknown case_id={fixture.case_id!r}")

    job = _replay_job(fixture, ordinal)
    if fixture.check_run is not None:
        assessment = assess_authenticated_runner_annotations(
            job,
            fixture.check_run,
            fixture.check_annotations,
        )
        if assessment is None:
            raise ValueError(
                f"Authenticated annotation replay did not produce evidence for {fixture.case_id}"
            )
    else:
        assessment = assess_job(job, fixture.log_excerpt)
    run_id = incident.ground_truth_run_id or (800_000 + ordinal)
    bundle = produce_ci_evidence_bundle(
        repo=incident.repository,
        run={
            "head_sha": fixture.head_sha or f"public-incident-replay-{ordinal}",
            "workflow_id": 700_000 + ordinal,
            "updated_at": "2026-09-30T00:00:00Z",
        },
        run_id=run_id,
        run_attempt=1,
        assessments=(assessment,),
    )
    decision = build_ci_retry_decision(bundle, max_attempts=2)

    reasons = decision.get("reasons") or []
    return PublicIncidentReplayResult(
        case_id=fixture.case_id,
        repository=incident.repository,
        expected_decision=fixture.expected_decision,
        actual_decision=str(decision.get("decision") or ""),
        evidence_status=str(decision.get("evidence_status") or ""),
        category=assessment.category,
        confidence=assessment.confidence,
        provenance_status=assessment.provenance_status,
        reason=str(reasons[0]) if reasons else "",
    )


def run_public_incident_replay() -> PublicIncidentReplaySummary:
    results = tuple(
        replay_public_incident(fixture, ordinal=index)
        for index, fixture in enumerate(PUBLIC_INCIDENT_REPLAY_FIXTURES_V5, start=1)
    )
    corpus_ids = {incident.case_id for incident in PUBLIC_INCIDENT_CORPUS_V5}
    replay_ids = {result.case_id for result in results}
    missing = tuple(sorted(corpus_ids - replay_ids))
    return PublicIncidentReplaySummary(
        results=results,
        missing_case_ids=missing,
        corpus_size=len(corpus_ids),
    )


def render_public_incident_replay(summary: PublicIncidentReplaySummary) -> str:
    lines = [
        "Public Incident Replay Gate v5",
        f"cases: {summary.replayed_cases}/{summary.corpus_size}",
        f"coverage: {summary.coverage:.0%}",
        f"false ALLOW: {summary.false_allows}",
        f"false BLOCK: {summary.false_blocks}",
        f"UNKNOWN evidence: {summary.unknown_evidence}",
        f"gate: {'PASS' if summary.gate_passed else 'FAIL'}",
        "",
    ]
    for result in summary.results:
        lines.append(
            f"{result.case_id}: expected={result.expected_decision} "
            f"actual={result.actual_decision} "
            f"category={result.category}/{result.confidence} "
            f"evidence={result.evidence_status}"
        )
    if summary.missing_case_ids:
        lines.append("")
        lines.append("missing replay fixtures: " + ", ".join(summary.missing_case_ids))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay public CI incidents through the production retry gate.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero on incomplete corpus coverage or any false authorization decision.",
    )
    args = parser.parse_args(argv)

    summary = run_public_incident_replay()
    print(render_public_incident_replay(summary), end="")
    if args.check and not summary.gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
