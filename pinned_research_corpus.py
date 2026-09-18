from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PinnedResearchCase:
    case_id: str
    repository: str
    run_id: int
    failed_attempt: int
    rerun_attempt: int
    failed_job_id: int
    rerun_job_id: int
    job_name: str
    failure_log: str
    failed_job: dict
    rerun_job: dict
    expected_runtime_category: str
    expected_mechanism_status: str
    expected_mechanism_reason: str
    expected_recovery_status: str
    expected_side_effect_risk: bool


SERDE_ATTESTATION_HTTP_500 = PinnedResearchCase(
    case_id="serde-attestation-http-500-2026-09-10",
    repository="serde-rs/serde",
    run_id=34427119351,
    failed_attempt=1,
    rerun_attempt=2,
    failed_job_id=102714612067,
    rerun_job_id=102722754676,
    job_name="Outdated",
    failure_log=(
        "2026-09-10T01:51:34.7155326Z ##[group]Run gh attestation verify "
        "--owner dtolnay /home/runner/.cargo/bin/cargo-outdated\n"
        "2026-09-10T01:52:16.4666726Z Error: HTTP 500: Server Error "
        "(https://api.github.com/orgs/dtolnay/attestations/sha256:<digest>"
        "?per_page=30&predicate_type=https%3A%2F%2Fslsa.dev%2Fprovenance%2Fv1)\n"
        "2026-09-10T01:52:16.4696205Z ##[error]Process completed with exit code 1.\n"
    ),
    failed_job={
        "id": 102714612067,
        "name": "Outdated",
        "conclusion": "failure",
        "started_at": "2026-09-10T01:51:21Z",
        "completed_at": "2026-09-10T01:52:18Z",
        "steps": [
            {
                "name": "Run actions/checkout@v7",
                "conclusion": "success",
                "started_at": "2026-09-10T01:51:23Z",
                "completed_at": "2026-09-10T01:51:24Z",
            },
            {
                "name": "Run dtolnay/rust-toolchain@stable",
                "conclusion": "success",
                "started_at": "2026-09-10T01:51:24Z",
                "completed_at": "2026-09-10T01:51:34Z",
            },
            {
                "name": "Run dtolnay/install@cargo-outdated",
                "conclusion": "failure",
                "started_at": "2026-09-10T01:51:34Z",
                "completed_at": "2026-09-10T01:52:16Z",
            },
        ],
    },
    rerun_job={
        "id": 102722754676,
        "name": "Outdated",
        "conclusion": "success",
        "started_at": "2026-09-10T02:32:10Z",
        "completed_at": "2026-09-10T02:32:28Z",
        "steps": [
            {
                "name": "Run actions/checkout@v7",
                "conclusion": "success",
                "started_at": "2026-09-10T02:32:12Z",
                "completed_at": "2026-09-10T02:32:13Z",
            },
            {
                "name": "Run dtolnay/rust-toolchain@stable",
                "conclusion": "success",
                "started_at": "2026-09-10T02:32:13Z",
                "completed_at": "2026-09-10T02:32:16Z",
            },
            {
                "name": "Run dtolnay/install@cargo-outdated",
                "conclusion": "success",
                "started_at": "2026-09-10T02:32:16Z",
                "completed_at": "2026-09-10T02:32:23Z",
            },
        ],
    },
    expected_runtime_category="UNKNOWN",
    expected_mechanism_status="TRANSIENT_MECHANISM_SUPPORTED",
    expected_mechanism_reason="SERVER_5XX",
    expected_recovery_status="VALIDATED_RECOVERY",
    expected_side_effect_risk=False,
)


PINNED_RESEARCH_CASES = (SERDE_ATTESTATION_HTTP_500,)
