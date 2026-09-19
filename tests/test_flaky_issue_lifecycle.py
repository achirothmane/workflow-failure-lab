import pytest

from flaky_issue_lifecycle import (
    ISSUE_MARKER_PREFIX,
    issue_fingerprint,
    issue_marker,
    issue_title,
    manage_issue_for_item,
    manage_issue_lifecycle,
    render_issue_body,
)
from flaky_quarantine_lifecycle import (
    BLOCKED_REGRESSION,
    RELEASED_HEALTHY,
)
from flaky_test_intelligence import DO_NOT_QUARANTINE, QUARANTINE_CANDIDATE
from flaky_triage import TriageItem


def item(test_id="pkg::test", status=QUARANTINE_CANDIDATE):
    return TriageItem(
        test_id=test_id,
        status=status,
        reason="evidence reason",
        failures=2,
        recoveries=2,
        persistent_failure_shas=0,
        waste_minutes=1.25,
        next_action="Investigate.",
        owners=("@team",),
        ownership_source="CODEOWNERS",
        ownership_route="tests",
        source_file="tests/test_x.py",
    )


class FakeAPI:
    def __init__(self, search_items=None):
        self.search_items = list(search_items or [])
        self.calls = []

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        self.calls.append((method, path, payload))
        if path.startswith("/search/issues"):
            return {"items": self.search_items}
        if method == "GET" and "/issues/" in path:
            number = int(path.rsplit("/", 1)[-1])
            for value in self.search_items:
                if int(value.get("number") or 0) == number:
                    return value
            return {}
        if method == "POST":
            return {"number": 100}
        if method == "PATCH":
            return {}
        raise AssertionError((method, path, payload))


def managed_issue(test_id, *, number=7, state="open", title=None, body=None):
    return {
        "number": number,
        "state": state,
        "title": title or issue_title(test_id),
        "body": body or render_issue_body(item(test_id), repo="o/r", run_id=1),
    }


def test_issue_identity_is_stable_and_test_specific():
    assert issue_fingerprint("pkg::a") == issue_fingerprint("pkg::a")
    assert issue_fingerprint("pkg::a") != issue_fingerprint("pkg::b")
    assert ISSUE_MARKER_PREFIX in issue_marker("pkg::a")
    assert issue_fingerprint("pkg::a")[:16] in issue_title("pkg::a")


def test_issue_body_links_owner_evidence_and_run_without_mentions():
    body = render_issue_body(item(), repo="o/r", run_id=42)

    assert "@team" in body
    assert "same-SHA recoveries: **2**" in body
    assert "https://github.com/o/r/actions/runs/42" in body
    assert issue_marker("pkg::test") in body


def test_actionable_item_creates_issue_when_none_exists():
    api = FakeAPI()

    action = manage_issue_for_item(api, "o/r", item(), run_id=42)

    assert action == "created"
    assert api.calls[-1][0] == "POST"
    assert api.calls[-1][1] == "/repos/o/r/issues"


def test_existing_managed_issue_is_updated_not_duplicated():
    test_id = "pkg::test"
    existing = managed_issue(test_id, body=issue_marker(test_id) + "\nold")
    api = FakeAPI([existing])

    action = manage_issue_for_item(api, "o/r", item(test_id), run_id=42)

    assert action == "updated"
    assert api.calls[-1][0] == "PATCH"
    assert api.calls[-1][1] == "/repos/o/r/issues/7"


def test_released_healthy_closes_existing_issue():
    test_id = "pkg::test"
    api = FakeAPI([managed_issue(test_id)])

    action = manage_issue_for_item(
        api,
        "o/r",
        item(test_id, RELEASED_HEALTHY),
        run_id=42,
    )

    assert action == "closed"
    assert api.calls[-1][2]["state"] == "closed"


def test_actionable_again_reopens_closed_issue():
    test_id = "pkg::test"
    api = FakeAPI([managed_issue(test_id, state="closed")])

    action = manage_issue_for_item(
        api,
        "o/r",
        item(test_id, BLOCKED_REGRESSION),
        run_id=42,
    )

    assert action == "reopened"
    assert api.calls[-1][2]["state"] == "open"


def test_do_not_quarantine_does_not_create_new_issue():
    api = FakeAPI()

    action = manage_issue_for_item(
        api,
        "o/r",
        item("pkg::plain-failure", DO_NOT_QUARANTINE),
        run_id=42,
    )

    assert action == "unchanged"
    assert not any(call[0] == "POST" for call in api.calls)


def test_issue_lifecycle_enforces_write_cap_and_defers_remaining():
    api = FakeAPI()
    items = (
        item("pkg::a"),
        item("pkg::b"),
        item("pkg::c"),
    )

    result = manage_issue_lifecycle(
        api,
        "o/r",
        items,
        run_id=42,
        max_changes=2,
    )

    assert result.created == 2
    assert result.deferred == 1


def test_issue_lifecycle_rejects_out_of_range_write_cap():
    api = FakeAPI()
    with pytest.raises(ValueError):
        manage_issue_lifecycle(
            api,
            "o/r",
            (item("pkg::a"),),
            run_id=42,
            max_changes=0,
        )
