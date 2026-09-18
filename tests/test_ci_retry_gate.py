import http.client

import ci_retry_gate
from ci_retry_gate import GitHubAPI, assess_job, classify_log, detect_side_effect_risk, rerun_decision


def fake_job(name="tests", steps=None, start="2026-09-17T01:00:00Z", end="2026-09-17T01:04:30Z"):
    return {
        "id": 42,
        "name": name,
        "started_at": start,
        "completed_at": end,
        "steps": steps or [],
    }


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
    assert result.score == 2


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
    a = assess_job(fake_job("install deps"), "ETIMEDOUT\nconnection reset by peer\ncould not resolve host")
    safe, reason = rerun_decision([a], run_attempt=1, max_attempts=2)
    assert safe is True
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
