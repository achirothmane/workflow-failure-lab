from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
D00 = ROOT / "experiments" / "d00"
SCHEMA = json.loads((D00 / "measurement.schema.json").read_text(encoding="utf-8"))
RECORD = json.loads((D00 / "dry-run-ci-native.json").read_text(encoding="utf-8"))

SECRET_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"Authorization:\s*Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
]


def test_d00_representative_dry_run_validates_against_schema() -> None:
    Draft202012Validator(
        SCHEMA,
        format_checker=FormatChecker(),
    ).validate(RECORD)


def test_d00_timestamp_and_identity_joins_are_present() -> None:
    assert RECORD["case_id"]
    assert RECORD["record_id"]
    assert RECORD["repository"]
    assert RECORD["workflow_ref"]
    assert RECORD["run_id"]
    assert RECORD["head_sha"]
    assert RECORD["run_attempt"] == 1
    assert RECORD["account_ref"]

    started = datetime.fromisoformat(RECORD["started_at"].replace("Z", "+00:00"))
    ended = datetime.fromisoformat(RECORD["ended_at"].replace("Z", "+00:00"))
    assert ended >= started
    assert (ended - started).total_seconds() == RECORD["elapsed_seconds"]


def test_d00_active_waiting_and_provider_time_do_not_double_count() -> None:
    active = RECORD["active_seconds"]
    waiting = RECORD["waiting_seconds"]
    elapsed = RECORD["elapsed_seconds"]
    provider = RECORD["provider_latency_seconds"]

    assert active + waiting <= elapsed
    assert provider <= waiting

    active_subcategories = sum(
        RECORD[name]
        for name in (
            "installation_active_seconds",
            "maintenance_active_seconds",
            "exception_active_seconds",
            "recovery_active_seconds",
        )
    )
    assert active_subcategories <= active


def test_d00_dry_run_cannot_masquerade_as_observed_baseline() -> None:
    assert RECORD["source_kind"] == "synthetic_dry_run"
    assert RECORD["notes_code"] == "SYNTHETIC_ONLY_NOT_BASELINE"
    assert RECORD["included"] is True


def test_d00_committed_fixture_contains_no_common_secret_material() -> None:
    text = (D00 / "dry-run-ci-native.json").read_text(encoding="utf-8")
    for pattern in SECRET_PATTERNS:
        assert not pattern.search(text), f"possible secret matched {pattern.pattern}"
    assert RECORD["secret_scan"] == "pass"


def test_d00_has_no_preregistered_percentage_savings_target() -> None:
    plan = (D00 / "comparator-plan.md").read_text(encoding="utf-8").lower()
    assert "universal percentage-savings target" in plan
    assert re.search(r"\b(?:[1-9]\d?|100)%\s+(?:savings|reduction|faster)", plan) is None


def test_d00_unknown_and_failed_cases_are_retained_by_rule() -> None:
    plan = (D00 / "comparator-plan.md").read_text(encoding="utf-8")
    assert "UNKNOWN/ambiguous closure" in plan
    assert "failures" in plan
    assert "Difficult cases cannot be dropped" in plan
