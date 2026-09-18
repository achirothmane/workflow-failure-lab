from mechanism_causality_gate import (
    MECHANISM_CAUSAL_CONFIRMED,
    MECHANISM_CAUSAL_UNCONFIRMED,
    assess_mechanism_causality,
)
from transient_mechanism_gate import REASON_SERVER_5XX


def failed_job(step_name="Run failing command"):
    return {
        "name": "test",
        "steps": [
            {
                "name": step_name,
                "conclusion": "failure",
                "started_at": "2026-09-18T01:00:00Z",
                "completed_at": "2026-09-18T01:01:00Z",
            }
        ],
    }


def test_serde_http_500_is_causal_inside_failed_step():
    result = assess_mechanism_causality(
        failed_job("Run dtolnay/install@cargo-outdated"),
        (
            "2026-09-18T01:00:10.0000000Z ##[group]Run gh attestation verify --owner dtolnay artifact\n"
            "2026-09-18T01:00:45.0000000Z Error: HTTP 500: Server Error (https://api.github.com/attestations)\n"
            "2026-09-18T01:00:46.0000000Z ##[error]Process completed with exit code 1.\n"
        ),
    )

    assert result.status == MECHANISM_CAUSAL_CONFIRMED
    assert result.reasons == (REASON_SERVER_5XX,)
    assert result.failed_step == "Run dtolnay/install@cargo-outdated"
    assert any("HTTP 500" in line for line in result.evidence)


def test_docker_timeout_cli_option_is_not_causal_mechanism():
    result = assess_mechanism_causality(
        failed_job(),
        (
            "2026-09-18T01:00:10.0000000Z go run gotest.tools/gotestsum@latest -- -timeout 20m ./pkg/e2e\n"
            "2026-09-18T01:00:40.0000000Z image_identity_corner_test.go:123: running command: docker compose down --timeout 10\n"
            "2026-09-18T01:00:50.0000000Z ##[error]Process completed with exit code 1.\n"
        ),
    )

    assert result.status == MECHANISM_CAUSAL_UNCONFIRMED
    assert result.reasons == ()


def test_typescript_timeout_test_option_is_not_causal_mechanism():
    result = assess_mechanism_causality(
        failed_job(),
        (
            "2026-09-18T01:00:10.0000000Z $ tools/gotestsum -- -tags=noembed ./... --timeout=45m\n"
            "2026-09-18T01:00:45.0000000Z error in test:tsc in 6m 22.1s\n"
            "2026-09-18T01:00:46.0000000Z ##[error]Process completed with exit code 1.\n"
        ),
    )

    assert result.status == MECHANISM_CAUSAL_UNCONFIRMED


def test_deno_timeout_package_and_branch_names_are_not_causal_mechanism():
    result = assess_mechanism_causality(
        failed_job(),
        (
            "2026-09-18T01:00:10.0000000Z downloaded wait-timeout v0.2.1\n"
            "2026-09-18T01:00:20.0000000Z * [new branch] fix/abort-signal-timeout-memory-leak -> upstream/fix/abort-signal-timeout-memory-leak\n"
            "2026-09-18T01:00:50.0000000Z ##[error]Process completed with exit code 1.\n"
        ),
    )

    assert result.status == MECHANISM_CAUSAL_UNCONFIRMED


def test_causal_transient_error_outside_failed_step_does_not_bind():
    result = assess_mechanism_causality(
        failed_job(),
        (
            "2026-09-18T00:59:30.0000000Z Error: HTTP 503: Service Unavailable\n"
            "2026-09-18T01:00:50.0000000Z ##[error]Process completed with exit code 1.\n"
        ),
    )

    assert result.status == MECHANISM_CAUSAL_UNCONFIRMED
