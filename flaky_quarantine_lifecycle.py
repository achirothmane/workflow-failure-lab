from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from ci_retry_gate import GitHubAPI
from flaky_test_intelligence import (
    DO_NOT_QUARANTINE,
    PASS,
    QUARANTINE_CANDIDATE,
    CaseObservation,
    FlakyTestSummary,
)

ACTIVE = "ACTIVE"
EXPIRED = "EXPIRED"
RELEASED_HEALTHY = "RELEASED_HEALTHY"
BLOCKED_REGRESSION = "BLOCKED_REGRESSION"
BLOCKED_UNVERIFIED = "BLOCKED_UNVERIFIED"


@dataclass(frozen=True)
class QuarantineEntry:
    test_id: str
    approved_by: str
    approved_at: datetime
    activated_run_id: int
    expires_at: datetime
    reason: str = ""


@dataclass(frozen=True)
class LifecycleDecision:
    test_id: str
    state: str
    reason: str
    clean_revision_streak: int = 0


@dataclass(frozen=True)
class LifecycleSummary:
    decisions: tuple[LifecycleDecision, ...]

    @property
    def active(self) -> tuple[LifecycleDecision, ...]:
        return tuple(item for item in self.decisions if item.state == ACTIVE)

    @property
    def expired(self) -> tuple[LifecycleDecision, ...]:
        return tuple(item for item in self.decisions if item.state == EXPIRED)

    @property
    def released(self) -> tuple[LifecycleDecision, ...]:
        return tuple(
            item for item in self.decisions
            if item.state == RELEASED_HEALTHY
        )

    @property
    def blocked(self) -> tuple[LifecycleDecision, ...]:
        return tuple(
            item for item in self.decisions
            if item.state in {BLOCKED_REGRESSION, BLOCKED_UNVERIFIED}
        )


def _parse_time(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("timestamp must be non-empty")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_manifest(text: str, *, max_days: int) -> tuple[QuarantineEntry, ...]:
    if max_days < 1 or max_days > 90:
        raise ValueError("max_days must be between 1 and 90")

    data = json.loads(text)
    if data.get("version") != 1:
        raise ValueError("quarantine manifest version must be 1")

    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("quarantine manifest entries must be a list")

    entries: list[QuarantineEntry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise ValueError("each quarantine entry must be an object")

        test_id = str(raw.get("test_id") or "").strip()
        approved_by = str(raw.get("approved_by") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        if not test_id:
            raise ValueError("quarantine test_id must be non-empty")
        if test_id in seen:
            raise ValueError(f"duplicate quarantine entry: {test_id}")
        if not approved_by:
            raise ValueError(f"approved_by is required for {test_id}")

        approved_at = _parse_time(str(raw.get("approved_at") or ""))
        expires_at = _parse_time(str(raw.get("expires_at") or ""))
        activated_run_id = int(raw.get("activated_run_id") or 0)
        if activated_run_id <= 0:
            raise ValueError(f"activated_run_id must be positive for {test_id}")
        if expires_at <= approved_at:
            raise ValueError(f"expires_at must be after approved_at for {test_id}")
        if (expires_at - approved_at).total_seconds() > max_days * 86400:
            raise ValueError(
                f"quarantine for {test_id} exceeds max_days={max_days}"
            )

        seen.add(test_id)
        entries.append(
            QuarantineEntry(
                test_id=test_id,
                approved_by=approved_by,
                approved_at=approved_at,
                activated_run_id=activated_run_id,
                expires_at=expires_at,
                reason=reason,
            )
        )

    return tuple(entries)


def load_manifest_from_github(
    api: GitHubAPI,
    repo: str,
    ref: str,
    path: str,
    *,
    max_days: int,
) -> tuple[QuarantineEntry, ...] | None:
    normalized = path.strip().lstrip("/")
    if not normalized:
        raise ValueError("quarantine manifest path must be non-empty")
    if not ref.strip():
        raise ValueError("quarantine manifest ref must be non-empty")

    encoded_path = quote(normalized, safe="/")
    encoded_ref = quote(ref, safe="")
    try:
        payload = api.request(
            "GET",
            f"/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}",
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise

    if not isinstance(payload, dict):
        raise ValueError("quarantine manifest response was not a file")
    encoded = str(payload.get("content") or "").replace("\n", "")
    if not encoded:
        raise ValueError("quarantine manifest file had no content")

    try:
        raw = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("quarantine manifest content was not valid UTF-8 base64") from exc

    return load_manifest(raw, max_days=max_days)


def clean_revision_streak(
    test_id: str,
    observations: tuple[CaseObservation, ...],
    *,
    after_run_id: int,
) -> int:
    by_sha: dict[str, list[CaseObservation]] = {}
    for item in observations:
        if item.test_id != test_id or item.run_id <= after_run_id:
            continue
        by_sha.setdefault(item.sha, []).append(item)

    revisions: list[tuple[int, str, list[CaseObservation]]] = []
    for sha, items in by_sha.items():
        newest_run = max(item.run_id for item in items)
        revisions.append((newest_run, sha, items))
    revisions.sort(reverse=True)

    streak = 0
    for _, _, items in revisions:
        statuses = {item.status for item in items}
        if statuses == {PASS}:
            streak += 1
            continue
        break
    return streak


def evaluate_lifecycle(
    entries: tuple[QuarantineEntry, ...],
    summaries: tuple[FlakyTestSummary, ...],
    observations: tuple[CaseObservation, ...],
    *,
    now: datetime,
    release_clean_shas: int,
) -> LifecycleSummary:
    if release_clean_shas < 1 or release_clean_shas > 20:
        raise ValueError("release_clean_shas must be between 1 and 20")
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now_utc = now.astimezone(timezone.utc)

    by_test = {item.test_id: item for item in summaries}
    decisions: list[LifecycleDecision] = []

    for entry in entries:
        if now_utc >= entry.expires_at:
            decisions.append(
                LifecycleDecision(
                    entry.test_id,
                    EXPIRED,
                    (
                        f"Temporary quarantine expired at "
                        f"{entry.expires_at.isoformat()}."
                    ),
                )
            )
            continue

        summary = by_test.get(entry.test_id)
        if summary is None:
            decisions.append(
                LifecycleDecision(
                    entry.test_id,
                    BLOCKED_UNVERIFIED,
                    "No current test-level evidence exists in the sampled history.",
                )
            )
            continue

        if (
            summary.persistent_failure_shas > 0
            or summary.recommendation == DO_NOT_QUARANTINE
        ):
            decisions.append(
                LifecycleDecision(
                    entry.test_id,
                    BLOCKED_REGRESSION,
                    (
                        "Current history contains an unresolved failure revision; "
                        "quarantine is suspended so a real regression cannot be hidden."
                    ),
                )
            )
            continue

        streak = clean_revision_streak(
            entry.test_id,
            observations,
            after_run_id=entry.activated_run_id,
        )
        if streak >= release_clean_shas:
            decisions.append(
                LifecycleDecision(
                    entry.test_id,
                    RELEASED_HEALTHY,
                    (
                        f"{streak} consecutive later code revisions were pass-only; "
                        "the test is automatically removed from the active quarantine set."
                    ),
                    clean_revision_streak=streak,
                )
            )
            continue

        if summary.recommendation != QUARANTINE_CANDIDATE:
            decisions.append(
                LifecycleDecision(
                    entry.test_id,
                    BLOCKED_UNVERIFIED,
                    (
                        "The current evidence no longer meets the conservative "
                        "QUARANTINE_CANDIDATE threshold."
                    ),
                    clean_revision_streak=streak,
                )
            )
            continue

        decisions.append(
            LifecycleDecision(
                entry.test_id,
                ACTIVE,
                (
                    f"Approved by {entry.approved_by}; temporary quarantine remains "
                    f"active until {entry.expires_at.isoformat()} unless health evidence "
                    "releases it earlier."
                ),
                clean_revision_streak=streak,
            )
        )

    decisions.sort(key=lambda item: (item.state, item.test_id))
    return LifecycleSummary(tuple(decisions))


def render_lifecycle_report(
    lifecycle: LifecycleSummary,
    *,
    manifest_path: str,
) -> str:
    lines = [
        "## Flaky Quarantine Lifecycle",
        "",
        f"Manifest: `{manifest_path}`",
        f"Active quarantines: **{len(lifecycle.active)}**",
        f"Expired quarantines: **{len(lifecycle.expired)}**",
        f"Automatically released as healthy: **{len(lifecycle.released)}**",
        f"Blocked or suspended: **{len(lifecycle.blocked)}**",
        "",
    ]

    if lifecycle.decisions:
        lines.extend(
            [
                "| Test | State | Clean revision streak | Reason |",
                "|---|---|---:|---|",
            ]
        )
        for item in lifecycle.decisions:
            test_id = item.test_id.replace("|", "/").replace("`", "'")
            reason = item.reason.replace("|", "/")
            lines.append(
                f"| `{test_id}` | `{item.state}` | "
                f"{item.clean_revision_streak} | {reason} |"
            )
    else:
        lines.append("The quarantine manifest contains no entries.")

    lines.extend(
        [
            "",
            "> Only `ACTIVE` entries belong to the effective quarantine set.",
            "> Expiry, insufficient evidence, or a persistent failure removes a test "
            "from the active set fail-closed. Healthy release requires later pass-only "
            "evidence on distinct code revisions.",
        ]
    )
    return "\n".join(lines) + "\n"


def active_test_ids_json(lifecycle: LifecycleSummary) -> str:
    return json.dumps(
        [item.test_id for item in lifecycle.active],
        separators=(",", ":"),
        ensure_ascii=True,
    )
