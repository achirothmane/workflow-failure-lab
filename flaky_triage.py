from __future__ import annotations

from dataclasses import dataclass

from ci_retry_gate import GitHubAPI
from flaky_quarantine_lifecycle import (
    ACTIVE,
    BLOCKED_REGRESSION,
    BLOCKED_UNVERIFIED,
    EXPIRED,
    RELEASED_HEALTHY,
    LifecycleSummary,
)
from flaky_test_intelligence import (
    DO_NOT_QUARANTINE,
    INVESTIGATE,
    QUARANTINE_CANDIDATE,
    FlakyTestSummary,
)
from flaky_ownership import OwnershipResolution

TRIAGE_COMMENT_MARKER = "<!-- ci-retry-gate-flaky-triage -->"
MAX_TRIAGE_ROWS = 20
MAX_ANNOTATIONS = 10


@dataclass(frozen=True)
class TriageItem:
    test_id: str
    status: str
    reason: str
    failures: int
    recoveries: int
    persistent_failure_shas: int
    waste_minutes: float
    next_action: str
    owners: tuple[str, ...] = ()
    ownership_source: str = "UNRESOLVED"
    ownership_route: str = ""
    source_file: str = ""


_PRIORITY = {
    BLOCKED_REGRESSION: 0,
    QUARANTINE_CANDIDATE: 1,
    ACTIVE: 2,
    EXPIRED: 3,
    BLOCKED_UNVERIFIED: 4,
    RELEASED_HEALTHY: 5,
    INVESTIGATE: 6,
    DO_NOT_QUARANTINE: 7,
}


def _next_action(status: str) -> str:
    return {
        BLOCKED_REGRESSION: "Treat as a possible regression; keep CI blocking and investigate.",
        QUARANTINE_CANDIDATE: "Human-review the evidence before adding a temporary manifest entry.",
        ACTIVE: "Keep executing the test; quarantine only masks its known failure from the gate.",
        EXPIRED: "Leave quarantine inactive; renew only after fresh evidence and human approval.",
        BLOCKED_UNVERIFIED: "Do not enforce quarantine until evidence is sufficient.",
        RELEASED_HEALTHY: "Remove the stale manifest entry; later revisions are healthy.",
        INVESTIGATE: "Collect more same-SHA evidence before quarantine.",
        DO_NOT_QUARANTINE: "Keep CI blocking; evidence does not support quarantine.",
    }.get(status, "Review the available evidence.")


def build_triage_items(
    summaries: tuple[FlakyTestSummary, ...],
    lifecycle: LifecycleSummary | None = None,
    ownership: dict[str, OwnershipResolution] | None = None,
) -> tuple[TriageItem, ...]:
    summary_by_id = {item.test_id: item for item in summaries}
    decision_by_id = (
        {item.test_id: item for item in lifecycle.decisions}
        if lifecycle is not None
        else {}
    )

    ordered_ids = [item.test_id for item in summaries]
    ordered_ids.extend(
        test_id for test_id in decision_by_id
        if test_id not in summary_by_id
    )

    ownership = ownership or {}
    items: list[TriageItem] = []
    for test_id in ordered_ids:
        summary = summary_by_id.get(test_id)
        decision = decision_by_id.get(test_id)
        status = decision.state if decision is not None else (
            summary.recommendation if summary is not None else BLOCKED_UNVERIFIED
        )
        reason = decision.reason if decision is not None else (
            summary.reason if summary is not None else "No matching test history summary."
        )
        owner = ownership.get(test_id)
        items.append(
            TriageItem(
                test_id=test_id,
                status=status,
                reason=reason,
                failures=summary.failures if summary is not None else 0,
                recoveries=summary.validated_recoveries if summary is not None else 0,
                persistent_failure_shas=(
                    summary.persistent_failure_shas if summary is not None else 0
                ),
                waste_minutes=(
                    summary.estimated_waste_minutes if summary is not None else 0.0
                ),
                next_action=_next_action(status),
                owners=owner.owners if owner is not None else (),
                ownership_source=owner.source if owner is not None else "UNRESOLVED",
                ownership_route=owner.route if owner is not None else "",
                source_file=owner.source_file if owner is not None else "",
            )
        )

    items.sort(
        key=lambda item: (
            _PRIORITY.get(item.status, 99),
            -item.waste_minutes,
            item.test_id,
        )
    )
    return tuple(items)


def _md(value: str) -> str:
    return (
        value.replace("|", "/")
        .replace(chr(96), "'")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _owner_cells(owners: tuple[str, ...]) -> str:
    if not owners:
        return "UNOWNED"
    return ", ".join(
        f"`{_md(owner)}`"
        for owner in owners
    )


def render_triage_report(
    items: tuple[TriageItem, ...],
    *,
    repo: str,
    run_id: int,
) -> str:
    lines = [
        TRIAGE_COMMENT_MARKER,
        "## Flaky Test Triage",
        "",
        f"Repository: {_md(repo)} · Run: {run_id}",
        "",
    ]

    if not items:
        lines.append("No flaky-test triage items were produced from the available evidence.")
        return "\n".join(lines) + "\n"

    active = sum(item.status == ACTIVE for item in items)
    candidates = sum(item.status == QUARANTINE_CANDIDATE for item in items)
    blocked = sum(
        item.status in {BLOCKED_REGRESSION, BLOCKED_UNVERIFIED}
        for item in items
    )
    released = sum(item.status == RELEASED_HEALTHY for item in items)
    total_waste = sum(item.waste_minutes for item in items)

    lines.extend(
        [
            f"**{len(items)} tests** · candidates **{candidates}** · active quarantines **{active}** · "
            f"blocked **{blocked}** · auto-released **{released}** · estimated waste **{total_waste:.2f} min**",
            "",
            "| Test | State | Owner | Route source | Evidence | Waste | Next action |",
            "|---|---|---|---|---|---:|---|",
        ]
    )

    for item in items[:MAX_TRIAGE_ROWS]:
        evidence = (
            f"{item.failures} failures · {item.recoveries} same-SHA recoveries · "
            f"{item.persistent_failure_shas} persistent SHAs"
        )
        lines.append(
            f"| {_md(item.test_id)} | {_md(item.status)} | "
            f"{_owner_cells(item.owners)} | {_md(item.ownership_source)} | "
            f"{_md(evidence)} | {item.waste_minutes:.2f} min | "
            f"{_md(item.next_action)} |"
        )

    if len(items) > MAX_TRIAGE_ROWS:
        lines.extend(
            [
                "",
                f"_Showing the first {MAX_TRIAGE_ROWS} of {len(items)} triage items._",
            ]
        )

    lines.extend(
        [
            "",
            "<details><summary>Why these decisions?</summary>",
            "",
        ]
    )
    for item in items[:MAX_TRIAGE_ROWS]:
        ownership_detail = (
            f"owners {_owner_cells(item.owners)} via {_md(item.ownership_source)}"
            if item.owners
            else "owner unresolved"
        )
        if item.source_file:
            ownership_detail += f"; source file {_md(item.source_file)}"
        if item.ownership_route:
            ownership_detail += f"; route {_md(item.ownership_route)}"
        lines.append(
            f"- {_md(item.test_id)} — **{_md(item.status)}**: {_md(item.reason)} "
            f"({ownership_detail})"
        )
    lines.extend(
        [
            "",
            "</details>",
            "",
            "> CI Retry Gate never auto-quarantines from detection alone. ACTIVE requires a human-approved manifest entry, and quarantined tests continue to execute so recovery or regression evidence remains observable.",
        ]
    )
    return "\n".join(lines) + "\n"


def resolve_pr_number(event: dict, current_run: dict) -> int | None:
    direct = event.get("pull_request")
    if isinstance(direct, dict):
        number = int(direct.get("number") or 0)
        if number > 0:
            return number

    workflow_run = event.get("workflow_run")
    sources = []
    if isinstance(workflow_run, dict):
        sources.append(workflow_run.get("pull_requests"))
    sources.append(current_run.get("pull_requests"))

    for raw in sources:
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            number = int(item.get("number") or 0)
            if number > 0:
                return number
    return None


def upsert_pr_comment(
    api: GitHubAPI,
    repo: str,
    pr_number: int,
    body: str,
) -> str:
    if pr_number <= 0:
        raise ValueError("pr_number must be positive")
    if TRIAGE_COMMENT_MARKER not in body:
        raise ValueError("triage comment marker is required")

    comments = api.request(
        "GET",
        f"/repos/{repo}/issues/{pr_number}/comments?per_page=100",
    )
    if not isinstance(comments, list):
        raise RuntimeError("GitHub comments response was not a list")

    for comment in comments:
        if not isinstance(comment, dict):
            continue
        existing = str(comment.get("body") or "")
        comment_id = int(comment.get("id") or 0)
        if TRIAGE_COMMENT_MARKER in existing and comment_id > 0:
            api.request(
                "PATCH",
                f"/repos/{repo}/issues/comments/{comment_id}",
                payload={"body": body},
            )
            return "updated"

    api.request(
        "POST",
        f"/repos/{repo}/issues/{pr_number}/comments",
        payload={"body": body},
    )
    return "created"


def _escape_command_message(value: str) -> str:
    return (
        value.replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def _escape_command_property(value: str) -> str:
    return (
        _escape_command_message(value)
        .replace(":", "%3A")
        .replace(",", "%2C")
    )


def emit_triage_annotations(
    items: tuple[TriageItem, ...],
    *,
    limit: int = MAX_ANNOTATIONS,
) -> int:
    if limit < 0:
        raise ValueError("limit must be non-negative")

    emitted = 0
    for item in items:
        if emitted >= limit:
            break

        level = "notice"
        if item.status in {
            QUARANTINE_CANDIDATE,
            BLOCKED_REGRESSION,
            BLOCKED_UNVERIFIED,
            EXPIRED,
            DO_NOT_QUARANTINE,
        }:
            level = "warning"

        title = _escape_command_property(f"Flaky test: {item.status}")
        owner_text = ", ".join(item.owners) if item.owners else "UNOWNED"
        message = _escape_command_message(
            f"{item.test_id} — owner: {owner_text} via {item.ownership_source}. "
            f"{item.next_action} Evidence: {item.failures} failures, "
            f"{item.recoveries} same-SHA recoveries, "
            f"{item.persistent_failure_shas} persistent SHAs, "
            f"{item.waste_minutes:.2f} min estimated waste."
        )
        print(f"::{level} title={title}::{message}")
        emitted += 1

    return emitted
