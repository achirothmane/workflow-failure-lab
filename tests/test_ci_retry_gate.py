from ci_retry_gate import assess_job, classify_log, detect_side_effect_risk, rerun_decision


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


def test_single_npm_econnreset_is_high_confidence():
    result = classify_log(
        "npm error code ECONNRESET\n"
        "Process completed with exit code 1"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence == "high"


def test_documentation_connect_timeout_does_not_become_high_confidence():
    result = classify_log(
        "data before giving up, as a float, or a (connect timeout, read timeout) tuple\n"
        "data before giving up, as a float, or a (connect timeout, read timeout) tuple\n"
        "Process completed with exit code 1"
    )
    assert result.category == "DEPENDENCY_NETWORK"
    assert result.confidence != "high"


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
