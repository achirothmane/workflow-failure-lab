from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import quote_plus

from ci_retry_gate import GitHubAPI
from flaky_quarantine_lifecycle import (
    ACTIVE,
    BLOCKED_REGRESSION,
    BLOCKED_UNVERIFIED,
    EXPIRED,
    RELEASED_HEALTHY,
)
from flaky_test_intelligence import (
    DO_NOT_QUARANTINE,
    INVESTIGATE,
    QUARANTINE_CANDIDATE,
)
from flaky_triage import TriageItem

ISSUE_MARKER_PREFIX = "<!-- ci-retry-gate-flaky-issue:"
DEFAULT_MAX_ISSUE_CHANGES = 10
MAX_ISSUE_CHANGES = 50

_CREATE_STATES = {
    BLOCKED_REGRESSION,
    QUARANTINE_CANDIDATE,
    INVESTIGATE,
    ACTIVE,
    EXPIRED,
    BLOCKED_UNVERIFIED,
}

_ISSUE_PRIORITY = {
    RELEASED_HEALTHY: 0,
    BLOCKED_REGRESSION: 1,
    QUARANTINE_CANDIDATE: 2,
    ACTIVE: 3,
    EXPIRED: 4,
    BLOCKED_UNVERIFIED: 5,
    INVESTIGATE: 6,
    DO_NOT_QUARANTINE: 7,
}


@dataclass(frozen=True)
class IssueLifecycleResult:
    created: int = 0
    updated: int = 0
    reopened: int = 0
    closed: int = 0
    unchanged: int = 0
    deferred: int = 0

    @property
    def managed(self) -> int:
        return self.created + self.updated + self.reopened + self.closed


def issue_fingerprint(test_id: str) -> str:
    value = test_id.strip()
    if not value:
        raise ValueError("test_id must be non-empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_marker(test_id: str) -> str:
    return f"{ISSUE_MARKER_PREFIX}{issue_fingerprint(test_id)} -->"


def issue_title(test_id: str) -> str:
    fingerprint = issue_fingerprint(test_id)[:16]
    normalized = " ".join(test_id.split())
    prefix = f"[CI Retry Gate][{fingerprint}] "
    max_test_chars = max(1, 220 - len(prefix))
    return prefix + normalized[:max_test_chars]


def _md(value: str) -> str:
    return (
        value.replace("|", "/")
        .replace(chr(96), "'")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _owner_text(item: TriageItem) -> str:
    if not item.owners:
        return "UNOWNED"
    return ", ".join(f"`{_md(owner)}`" for owner in item.owners)


def render_issue_body(
    item: TriageItem,
    *,
    repo: str,
    run_id: int,
) -> str:
    marker = issue_marker(item.test_id)
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}"
    lines = [
        marker,
        "## CI Retry Gate flaky-test investigation",
        "",
        f"**Test:** `{_md(item.test_id)}`",
        f"**Current state:** `{_md(item.status)}`",
        f"**Owner:** {_owner_text(item)}",
        f"**Ownership source:** `{_md(item.ownership_source)}`",
    ]
    if item.ownership_route:
        lines.append(f"**Route:** `{_md(item.ownership_route)}`")
    if item.source_file:
        lines.append(f"**Source file:** `{_md(item.source_file)}`")

    lines.extend(
        [
            "",
            "### Current evidence",
            "",
            f"- failures: **{item.failures}**",
            f"- same-SHA recoveries: **{item.recoveries}**",
            f"- persistent-failure SHAs: **{item.persistent_failure_shas}**",
            f"- estimated CI waste: **{item.waste_minutes:.2f} min**",
            "",
            f"**Reason:** {_md(item.reason)}",
            "",
            f"**Next action:** {_md(item.next_action)}",
            "",
            f"Latest analyzed run: {run_url}",
            "",
            "> This issue is managed by CI Retry Gate. Repeated runs update the same issue. "
            "Only RELEASED_HEALTHY closes it automatically; issue lifecycle does not authorize "
            "reruns or quarantines.",
        ]
    )
    return "\n".join(lines) + "\n"


def _issue_number(item: object) -> int:
    if not isinstance(item, dict):
        return 0
    try:
        return int(item.get("number") or 0)
    except (TypeError, ValueError):
        return 0


def _matching_managed_issue(
    candidates: object,
    marker: str,
) -> dict | None:
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("pull_request"):
            continue
        if marker in str(candidate.get("body") or ""):
            return candidate
    return None


def find_managed_issue(
    api: GitHubAPI,
    repo: str,
    test_id: str,
) -> dict | None:
    marker = issue_marker(test_id)

    recent = api.request(
        "GET",
        f"/repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=100",
    )
    if not isinstance(recent, list):
        raise RuntimeError("GitHub recent issues response was not a list")
    match = _matching_managed_issue(recent, marker)
    if match is not None:
        return match

    fingerprint = issue_fingerprint(test_id)[:16]
    query = quote_plus(
        f'repo:{repo} is:issue in:title "CI Retry Gate" "{fingerprint}"'
    )
    data = api.request(
        "GET",
        f"/search/issues?q={query}&per_page=20",
    )
    if not isinstance(data, dict):
        raise RuntimeError("GitHub issue search response was not an object")

    for candidate in data.get("items") or []:
        number = _issue_number(candidate)
        if number <= 0 or candidate.get("pull_request"):
            continue

        body = str(candidate.get("body") or "")
        if marker not in body:
            issue = api.request("GET", f"/repos/{repo}/issues/{number}")
            if not isinstance(issue, dict):
                continue
            body = str(issue.get("body") or "")
            candidate = issue

        if marker in body and not candidate.get("pull_request"):
            return candidate
    return None


def _patch_issue(
    api: GitHubAPI,
    repo: str,
    number: int,
    *,
    title: str,
    body: str,
    state: str,
) -> None:
    api.request(
        "PATCH",
        f"/repos/{repo}/issues/{number}",
        payload={
            "title": title,
            "body": body,
            "state": state,
        },
    )


def _needs_body_update(existing: dict, title: str, body: str) -> bool:
    return (
        str(existing.get("title") or "") != title
        or str(existing.get("body") or "") != body
    )


def manage_issue_for_item(
    api: GitHubAPI,
    repo: str,
    item: TriageItem,
    *,
    run_id: int,
) -> str:
    existing = find_managed_issue(api, repo, item.test_id)
    title = issue_title(item.test_id)
    body = render_issue_body(item, repo=repo, run_id=run_id)

    if item.status == RELEASED_HEALTHY:
        if existing is None:
            return "unchanged"
        number = _issue_number(existing)
        if str(existing.get("state") or "") == "closed":
            return "unchanged"
        _patch_issue(
            api,
            repo,
            number,
            title=title,
            body=body,
            state="closed",
        )
        return "closed"

    should_exist = item.status in _CREATE_STATES or (
        item.status == DO_NOT_QUARANTINE and existing is not None
    )
    if not should_exist:
        return "unchanged"

    if existing is None:
        api.request(
            "POST",
            f"/repos/{repo}/issues",
            payload={
                "title": title,
                "body": body,
            },
        )
        return "created"

    number = _issue_number(existing)
    state = str(existing.get("state") or "open")
    if state == "closed":
        _patch_issue(
            api,
            repo,
            number,
            title=title,
            body=body,
            state="open",
        )
        return "reopened"

    if _needs_body_update(existing, title, body):
        _patch_issue(
            api,
            repo,
            number,
            title=title,
            body=body,
            state="open",
        )
        return "updated"

    return "unchanged"


def manage_issue_lifecycle(
    api: GitHubAPI,
    repo: str,
    items: tuple[TriageItem, ...],
    *,
    run_id: int,
    max_changes: int = DEFAULT_MAX_ISSUE_CHANGES,
) -> IssueLifecycleResult:
    if max_changes < 1 or max_changes > MAX_ISSUE_CHANGES:
        raise ValueError(
            f"max_changes must be between 1 and {MAX_ISSUE_CHANGES}"
        )

    ordered = sorted(
        items,
        key=lambda item: (
            _ISSUE_PRIORITY.get(item.status, 99),
            -item.waste_minutes,
            item.test_id,
        ),
    )

    counts = {
        "created": 0,
        "updated": 0,
        "reopened": 0,
        "closed": 0,
        "unchanged": 0,
    }
    deferred = 0

    for item in ordered:
        if sum(
            counts[key]
            for key in ("created", "updated", "reopened", "closed")
        ) >= max_changes:
            if item.status in _CREATE_STATES or item.status == RELEASED_HEALTHY:
                deferred += 1
            continue

        action = manage_issue_for_item(
            api,
            repo,
            item,
            run_id=run_id,
        )
        counts[action] += 1

    return IssueLifecycleResult(
        created=counts["created"],
        updated=counts["updated"],
        reopened=counts["reopened"],
        closed=counts["closed"],
        unchanged=counts["unchanged"],
        deferred=deferred,
    )
