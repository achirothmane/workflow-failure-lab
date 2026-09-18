import http.client

import ci_retry_gate
from ci_retry_gate import AMBIGUOUS, CAUSAL, FAILURE_STEP_AMBIGUOUS, FAILURE_STEP_CONFIRMED, NON_CAUSAL, PROVENANCE_CONFIRMED, PROVENANCE_MISMATCH, PROVENANCE_UNAVAILABLE, TRANSIENT_CATEGORIES, GitHubAPI, assess_failure_step_provenance, assess_job, causal_evidence_role, classify_log, detect_side_effect_risk, rerun_decision


def fake_job(name="tests", steps=None, start="2026-09-17T01:00:00Z", end="2026-09-17T01:04:30Z"):
    return {
        "id": 42,
        "name": name,
        "started_at": start,
        "completed_at": end,
        "steps": steps or [],
    }


def failed_step(name="Install dependencies", start="2026-09-17T01:01:00Z", end="2026-09-17T01:02:00Z"):
    return {
        "name": name,
        "conclusion": "failure",
        "started_at": start,
        "completed_at": end,
    }


def timestamped_network_log(signal_time="2026-09-17T01:01:30.0000000Z"):
    return (
        "2026-09-17T01:01:00.1000000Z ##[group]Run npm ci\n"
        f"{signal_time} npm ERR! code ETIMEDOUT\n"
        "2026-09-17T01:01:31.0000000Z Error: connection reset by peer\n"
        "2026-09-17T01:01:32.0000000Z Process completed with exit code 1\n"
    )


def test_network_transient_high_confidence():
    result = classify_log("""
    npm ERR! code ETIMEDOUT
    connect ETIMEDOUT 104.20.22.46:443
    Error: connection reset by peer
    """)
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"


def test_single_read_tcp_connection_reset_is_high_confidence():
    result = classify_log(
        "read tcp 10.1.1.37:36338->13.226.53.57:443: read: connection reset by peer\n"
        "Process completed with exit code 1"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"


def test_ansi_colored_read_tcp_connection_reset_is_high_confidence():
    result = classify_log(
        "\x1b[31m│\x1b[0m \x1b[0mread tcp 10.1.1.37:36338->13.226.53.57:443: "
        "read: connection reset by peer\n"
        "\x1b[31m╵\x1b[0m\n"
        "Process completed with exit code 1"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"
    assert all("\x1b" not in line for line in result.evidence)


def test_single_npm_econnreset_is_high_confidence():
    result = classify_log(
        "npm error code ECONNRESET\n"
        "Process completed with exit code 1"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"


def test_documentation_connect_timeout_fails_closed_as_unknown():
    result = classify_log(
        "2026-08-24T16:58:07.7655465Z             data before giving up, as a float, or a :ref:\`(connect timeout,\n"
        "2026-08-24T16:58:07.7709068Z             data before giving up, as a float, or a :ref:\`(connect timeout,\n"
        "2026-08-24T16:58:08.0000000Z Process completed with exit code 1"
    )
    assert result.category == "UNKNOWN"
    assert result.confidence == "low"


def test_duplicate_timestamped_transient_prose_is_scored_once():
    result = classify_log(
        "2026-08-24T16:58:07.7655465Z connection timed out\n"
        "2026-08-24T16:58:07.7709068Z connection timed out\n"
    )
    assert result.category == "UNKNOWN"
    assert result.score == 1


def test_single_429_signal_remains_low_confidence_transient():
    result = classify_log("HTTP 429 Too Many Requests")
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "low"
    assert result.score == 3


def test_code_failure_is_not_transient():
    result = classify_log("AssertionError: expected 2 == 3\nTests failed\nProcess completed with exit code 1")
    assert result.category == "CODE_REGRESSION"
    assert result.confidence in {"medium", "high"}


def test_unknown_fails_closed():
    result = classify_log("something odd happened with no known signature")
    assert result.category == "UNKNOWN"
    assert result.confidence == "low"


def test_secret_redaction_in_evidence():
    result = classify_log("token=github_pat_abcdefghijklmnopqrstuvwxyz1234567890 ETIMEDOUT")
    assert result.category == "DEPENDENCY_NETWORK"
    assert all("github_pat_" not in line for line in result.evidence)


def test_detect_deploy_side_effect():
    risk, evidence = detect_side_effect_risk(fake_job("deploy production"))
    assert risk is True
    assert evidence


def test_detect_publish_step_side_effect():
    risk, evidence = detect_side_effect_risk(fake_job("build", [{"name": "npm publish"}]))
    assert risk is True
    assert evidence == ("npm publish",)


def test_safe_rerun_requires_all_failed_jobs_safe():
    a = assess_job(fake_job("install deps"), "ETIMEDOUT\nconnection reset by peer\ncould not resolve host")
    b = assess_job(fake_job("compile"), "AssertionError\nTests failed")
    safe, reason = rerun_decision([a, b], run_attempt=1, max_attempts=2)
    assert safe is False
    assert "compile" in reason


def test_safe_rerun_for_transient_without_side_effects():
    a = assess_job(
        fake_job("install deps", [failed_step()]),
        timestamped_network_log(),
    )
    safe, reason = rerun_decision([a], run_attempt=1, max_attempts=2)
    assert safe is True
    assert a.provenance_status == PROVENANCE_CONFIRMED
    assert "high-confidence transient" in reason


def test_side_effect_blocks_transient_rerun():
    a = assess_job(fake_job("deploy production"), "ETIMEDOUT\nconnection reset by peer\ncould not resolve host")
    safe, reason = rerun_decision([a], run_attempt=1, max_attempts=2)
    assert safe is False
    assert "side-effect" in reason


def test_attempt_cap_blocks_loop():
    a = assess_job(fake_job("install deps"), "ETIMEDOUT\nconnection reset by peer\ncould not resolve host")
    safe, reason = rerun_decision([a], run_attempt=2, max_attempts=2)
    assert safe is False
    assert "max_attempts" in reason


def test_duration_is_measured():
    a = assess_job(fake_job(), "ETIMEDOUT\nconnection reset by peer\ncould not resolve host")
    assert a.duration_minutes == 4.5


class _FakeHTTPResponse:
    def __init__(self, body: bytes | None = None, error: BaseException | None = None):
        self.body = body
        self.error = error
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if self.error is not None:
            raise self.error
        return self.body or b"{}"


class _SequenceOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def open(self, req, timeout=30):
        self.calls += 1
        return self.responses.pop(0)


def test_github_api_retries_incomplete_get_response(monkeypatch):
    api = GitHubAPI("token")
    api.opener = _SequenceOpener(
        [
            _FakeHTTPResponse(
                error=http.client.IncompleteRead(b'{"partial":', 10)
            ),
            _FakeHTTPResponse(body=b'{"ok": true}'),
        ]
    )
    monkeypatch.setattr(ci_retry_gate.time, "sleep", lambda _seconds: None)

    result = api.request("GET", "/repos/acme/repo/actions/runs")

    assert result == {"ok": True}
    assert api.opener.calls == 2


def test_github_api_does_not_retry_post_on_incomplete_response(monkeypatch):
    api = GitHubAPI("token")
    api.opener = _SequenceOpener(
        [
            _FakeHTTPResponse(
                error=http.client.IncompleteRead(b"", 10)
            ),
            _FakeHTTPResponse(body=b'{"unexpected": true}'),
        ]
    )
    monkeypatch.setattr(ci_retry_gate.time, "sleep", lambda _seconds: None)

    try:
        api.request("POST", "/repos/acme/repo/actions/runs/1/rerun", payload={})
    except RuntimeError as exc:
        assert "after 1 transport attempts" in str(exc)
    else:
        raise AssertionError("POST transport interruption must fail closed")

    assert api.opener.calls == 1


def test_requests_httpbin_handshake_timeout_is_not_auto_rerun_transient():
    result = classify_log(
        "2026-08-24T16:58:07.7655465Z data before giving up, as a float, or a :ref:\`(connect timeout,\n"
        "2026-08-24T16:58:07.7709068Z data before giving up, as a float, or a :ref:\`(connect timeout,\n"
        "2026-08-24T16:59:01.0000000Z pytest-httpbin server hit an exception serving request: "
        "_ssl.c:1015: The handshake operation timed out\n"
        "2026-08-24T16:59:02.0000000Z Process completed with exit code 1\n"
    )

    assert result.category == "RESOURCE_TIMEOUT"
    assert result.confidence == "low"
    assert result.category not in TRANSIENT_CATEGORIES
    assert result.evidence == (
        "pytest-httpbin server hit an exception serving request: "
        "_ssl.c:1015: The handshake operation timed out",
    )


def test_causal_evidence_rejects_documentation_role():
    line = "data before giving up, as a float, or a :ref:\`(connect timeout, read timeout) tuple"
    assert causal_evidence_role(line) == NON_CAUSAL


def test_causal_evidence_rejects_shell_comment():
    assert causal_evidence_role("# Error: connection reset by peer") == NON_CAUSAL


def test_causal_evidence_rejects_echoed_failure_example():
    assert causal_evidence_role('echo "Error: connection reset by peer"') == NON_CAUSAL


def test_causal_evidence_accepts_operational_error():
    assert causal_evidence_role("Error: connection reset by peer") == CAUSAL


def test_causal_evidence_accepts_curl_transport_error():
    assert causal_evidence_role("curl: (28) Operation timed out after 30000 milliseconds") == CAUSAL


def test_causal_evidence_keeps_unknown_text_ambiguous():
    assert causal_evidence_role("connection timed out") == AMBIGUOUS


def test_documented_connection_reset_does_not_become_transient():
    result = classify_log(
        "2026-09-18T01:00:00.0000000Z # Error: connection reset by peer\n"
        "2026-09-18T01:00:00.1000000Z echo \"Error: connection reset by peer\"\n"
        "2026-09-18T01:00:00.2000000Z Process completed with exit code 1\n"
    )
    assert result.category == "UNKNOWN"
    assert result.confidence == "low"


def test_real_connection_reset_survives_causal_filter():
    result = classify_log(
        "2026-09-18T01:00:00.0000000Z Error: connection reset by peer\n"
        "2026-09-18T01:00:00.1000000Z Process completed with exit code 1\n"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"
    assert result.evidence == ("Error: connection reset by peer",)


def test_ambiguous_timeout_hint_is_discounted():
    result = classify_log("connection timed out")
    assert result.category == "UNKNOWN"
    assert result.score == 1


def test_execution_provenance_binds_signal_to_failed_step_and_command():
    assessment = assess_job(
        fake_job("install deps", [failed_step()]),
        timestamped_network_log(),
    )
    assert assessment.category == "DEPENDENCY_NETWORK"
    assert assessment.confidence == "high"
    assert assessment.provenance_status == PROVENANCE_CONFIRMED
    assert assessment.provenance_step == "Install dependencies"
    assert assessment.provenance_command == "npm ci"
    assert any("signal: npm ERR! code ETIMEDOUT" in item for item in assessment.provenance_evidence)
    assert any("exit: Process completed with exit code 1" in item for item in assessment.provenance_evidence)


def test_execution_provenance_fails_closed_without_timestamps():
    assessment = assess_job(
        fake_job("install deps", [failed_step()]),
        "npm ERR! code ETIMEDOUT\nError: connection reset by peer\n",
    )
    assert assessment.category == "DEPENDENCY_NETWORK"
    assert assessment.confidence == "high"
    assert assessment.provenance_status == PROVENANCE_UNAVAILABLE

    safe, reason = rerun_decision([assessment], run_attempt=1, max_attempts=2)
    assert safe is False
    assert "Execution provenance" in reason


def test_execution_provenance_detects_signal_outside_failed_step_window():
    assessment = assess_job(
        fake_job("install deps", [failed_step()]),
        (
            "2026-09-17T01:03:29.0000000Z ##[group]Run npm ci\n"
            "2026-09-17T01:03:30.0000000Z npm ERR! code ETIMEDOUT\n"
            "2026-09-17T01:03:31.0000000Z Error: connection reset by peer\n"
            "2026-09-17T01:03:32.0000000Z Process completed with exit code 1\n"
        ),
    )
    assert assessment.category == "DEPENDENCY_NETWORK"
    assert assessment.confidence == "high"
    assert assessment.provenance_status == PROVENANCE_MISMATCH

    safe, reason = rerun_decision([assessment], run_attempt=1, max_attempts=2)
    assert safe is False
    assert "MISMATCH" in reason


def test_git_new_branch_ref_with_error_token_is_non_causal():
    line = "* [new branch] fix/http-client-spurious-econnreset -> upstream/fix/http-client-spurious-econnreset"
    assert causal_evidence_role(line) == NON_CAUSAL


def test_git_ref_names_do_not_create_dependency_network_classification():
    result = classify_log(
        "2026-09-16T12:04:37.0410523Z  * [new branch] fix/http-client-spurious-econnreset -> upstream/fix/http-client-spurious-econnreset\n"
        "2026-09-16T12:04:52.4008814Z  * [new branch] fix/http-client-spurious-econnreset -> origin/fix/http-client-spurious-econnreset\n"
        "2026-09-16T12:05:24.9938186Z  ! [rejected] HEAD -> release_2_9.7 (non-fast-forward)\n"
        "2026-09-16T12:05:24.9939182Z error: failed to push some refs to 'https://github.com/denoland/deno'\n"
        "2026-09-16T12:05:25.0159723Z Process completed with exit code 1.\n"
    )
    assert result.category != "DEPENDENCY_NETWORK"


def test_create_pr_step_is_side_effect():
    risk, evidence = detect_side_effect_risk(
        fake_job("version bump", [{"name": "Create PR"}])
    )
    assert risk is True
    assert evidence == ("Create PR",)


def test_git_push_step_is_side_effect():
    risk, evidence = detect_side_effect_risk(
        fake_job("helper", [{"name": "git push origin HEAD"}])
    )
    assert risk is True
    assert evidence == ("git push origin HEAD",)


def test_failure_step_provenance_is_independent_from_unknown_classification():
    job = fake_job("mystery", [failed_step("Mystery operation")])
    assessment = assess_job(job, "Error: mysterious subsystem exploded")

    assert assessment.category == "UNKNOWN"
    assert assessment.failure_step_status == FAILURE_STEP_CONFIRMED
    assert assessment.failure_step == "Mystery operation"

    safe, _ = rerun_decision([assessment], run_attempt=1, max_attempts=2)
    assert safe is False


def test_failure_step_provenance_is_ambiguous_with_multiple_failed_steps():
    result = assess_failure_step_provenance(
        fake_job(
            "multi",
            [
                failed_step("Step A"),
                failed_step("Step B"),
            ],
        )
    )

    assert result.status == FAILURE_STEP_AMBIGUOUS
    assert result.step_name == ""
    assert "Step A" in result.evidence[0]
    assert "Step B" in result.evidence[0]

