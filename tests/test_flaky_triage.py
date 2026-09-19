from flaky_ownership import OwnershipResolution
from flaky_quarantine_lifecycle import (
    ACTIVE,
    BLOCKED_REGRESSION,
    LifecycleDecision,
    LifecycleSummary,
)
from flaky_test_intelligence import (
    INVESTIGATE,
    QUARANTINE_CANDIDATE,
    FlakyTestSummary,
)
from flaky_triage import (
    TRIAGE_COMMENT_MARKER,
    build_triage_items,
    emit_triage_annotations,
    render_triage_report,
    resolve_pr_number,
    upsert_pr_comment,
)


def summary(
    test_id: str,
    *,
    recommendation: str,
    failures: int = 2,
    recoveries: int = 2,
    persistent: int = 0,
    waste_seconds: float = 120.0,
    reason: str = "evidence reason",
) -> FlakyTestSummary:
    return FlakyTestSummary(
        test_id=test_id,
        observations=4,
        failures=failures,
        passes=2,
        same_sha_flips=recoveries,
        validated_recoveries=recoveries,
        persistent_failure_shas=persistent,
        failed_seconds=waste_seconds / 2,
        recovery_seconds=waste_seconds / 2,
        estimated_waste_seconds=waste_seconds,
        recommendation=recommendation,
        reason=reason,
    )


def test_triage_prioritizes_blocked_regression_over_candidate():
    summaries = (
        summary("pkg::candidate", recommendation=QUARANTINE_CANDIDATE),
        summary("pkg::regression", recommendation=INVESTIGATE, persistent=1),
    )
    lifecycle = LifecycleSummary(
        decisions=(
            LifecycleDecision(
                test_id="pkg::regression",
                state=BLOCKED_REGRESSION,
                reason="persistent failure observed",
            ),
        )
    )

    items = build_triage_items(summaries, lifecycle)

    assert [item.test_id for item in items] == [
        "pkg::regression",
        "pkg::candidate",
    ]
    assert items[0].status == BLOCKED_REGRESSION
    assert "possible regression" in items[0].next_action


def test_triage_report_contains_marker_evidence_and_action():
    items = build_triage_items(
        (summary("pkg.TestCart::test_total", recommendation=QUARANTINE_CANDIDATE),)
    )

    report = render_triage_report(items, repo="o/r", run_id=42)

    assert TRIAGE_COMMENT_MARKER in report
    assert "Flaky Test Triage" in report
    assert "2 same-SHA recoveries" in report
    assert "Human-review the evidence" in report
    assert "CI Retry Gate never auto-quarantines" in report


def test_lifecycle_state_overrides_detector_recommendation():
    summaries = (
        summary("pkg::flaky", recommendation=QUARANTINE_CANDIDATE),
    )
    lifecycle = LifecycleSummary(
        decisions=(
            LifecycleDecision(
                test_id="pkg::flaky",
                state=ACTIVE,
                reason="approved and still supported",
            ),
        )
    )

    items = build_triage_items(summaries, lifecycle)

    assert items[0].status == ACTIVE
    assert "Keep executing the test" in items[0].next_action


def test_resolve_pr_number_prefers_direct_event_then_workflow_run():
    direct = {"pull_request": {"number": 17}}
    assert resolve_pr_number(direct, {}) == 17

    event = {"workflow_run": {"pull_requests": [{"number": 23}]}}
    assert resolve_pr_number(event, {}) == 23

    current_run = {"pull_requests": [{"number": 31}]}
    assert resolve_pr_number({}, current_run) == 31
    assert resolve_pr_number({}, {}) is None


class FakeCommentAPI:
    def __init__(self, comments=None):
        self.comments = list(comments or [])
        self.calls = []

    def request(self, method, path, payload=None, accept="application/vnd.github+json"):
        self.calls.append((method, path, payload))
        if method == "GET":
            return self.comments
        return {}


def test_upsert_pr_comment_creates_when_marker_absent():
    api = FakeCommentAPI([{"id": 1, "body": "another bot"}])
    body = TRIAGE_COMMENT_MARKER + "\nreport"

    action = upsert_pr_comment(api, "o/r", 7, body)

    assert action == "created"
    assert api.calls[-1] == (
        "POST",
        "/repos/o/r/issues/7/comments",
        {"body": body},
    )


def test_upsert_pr_comment_updates_existing_marker_comment():
    api = FakeCommentAPI(
        [{"id": 99, "body": TRIAGE_COMMENT_MARKER + "\nold report"}]
    )
    body = TRIAGE_COMMENT_MARKER + "\nnew report"

    action = upsert_pr_comment(api, "o/r", 7, body)

    assert action == "updated"
    assert api.calls[-1] == (
        "PATCH",
        "/repos/o/r/issues/comments/99",
        {"body": body},
    )


def test_annotations_are_bounded_and_escape_workflow_commands(capsys):
    items = build_triage_items(
        (
            summary(
                "pkg::test%name\nline",
                recommendation=QUARANTINE_CANDIDATE,
            ),
            summary("pkg::second", recommendation=INVESTIGATE),
        )
    )

    emitted = emit_triage_annotations(items, limit=1)
    output = capsys.readouterr().out

    assert emitted == 1
    assert output.count("::warning") == 1
    assert "%25" in output
    assert "%0A" in output
    assert "pkg::second" not in output


def test_triage_report_surfaces_owner_without_github_mention_side_effect():
    test_id = "pkg.TestCart::test_total"
    ownership = {
        test_id: OwnershipResolution(
            test_id=test_id,
            owners=("@payments-team",),
            source="CODEOWNERS",
            matched_pattern="/tests/payments/**",
            source_file="tests/payments/test_cart.py",
            route="CODEOWNERS",
        )
    }
    items = build_triage_items(
        (summary(test_id, recommendation=QUARANTINE_CANDIDATE),),
        ownership=ownership,
    )

    report = render_triage_report(items, repo="o/r", run_id=42)

    assert "| `@payments-team` | CODEOWNERS |" in report
    assert "source file tests/payments/test_cart.py" in report
    assert "owners `@payments-team` via CODEOWNERS" in report
