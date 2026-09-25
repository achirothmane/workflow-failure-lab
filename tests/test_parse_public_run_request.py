from scripts.parse_public_run_request import parse_request


def event_for(body: str) -> dict:
    return {"issue": {"body": body}}


def test_parse_public_run_request():
    valid, repo, run_id, attempt, error = parse_request(
        event_for(
            """### Public repository
acme/widgets

### Workflow run ID
123456

### Run attempt (optional)
2

### Context (optional)
flaky CI
"""
        )
    )

    assert valid is True
    assert repo == "acme/widgets"
    assert run_id == "123456"
    assert attempt == "2"
    assert error == ""


def test_parse_public_run_request_allows_empty_attempt():
    valid, repo, run_id, attempt, error = parse_request(
        event_for(
            """### Public repository
acme/widgets

### Workflow run ID
123456

### Run attempt (optional)
_No response_
"""
        )
    )

    assert valid is True
    assert attempt == ""
    assert error == ""


def test_parse_public_run_request_rejects_injection_like_repository():
    valid, *_rest, error = parse_request(
        event_for(
            """### Public repository
acme/widgets; echo pwned

### Workflow run ID
123456
"""
        )
    )

    assert valid is False
    assert "owner/repo" in error
