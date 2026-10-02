from __future__ import annotations

import json

import pytest

from effect_plan import (
    EffectPlanError,
    build_effect_plan,
    read_effect_plan,
    write_effect_plan,
)


def _decision() -> dict:
    return {
        "scope": {
            "repository": "owner/repo",
            "run_id": 123,
            "run_attempt": 1,
            "head_sha": "abc123",
            "workflow_id": 99,
        }
    }


def test_effect_plan_round_trip_is_digest_verified(tmp_path) -> None:
    plan = build_effect_plan(
        mutation_admitted=True,
        repository="owner/repo",
        run_id=123,
        evidence_decision=_decision(),
        failed_jobs=[{"id": 7, "conclusion": "failure"}],
        decision_record_sha256="a" * 64,
    )
    path = tmp_path / "effect-plan.json"
    digest = write_effect_plan(path, plan)

    loaded = read_effect_plan(path, expected_sha256=digest)
    assert loaded["mutation_admitted"] is True
    assert loaded["failed_jobs"] == [{"id": 7, "conclusion": "failure"}]


def test_effect_plan_tamper_is_rejected(tmp_path) -> None:
    plan = build_effect_plan(
        mutation_admitted=True,
        repository="owner/repo",
        run_id=123,
        evidence_decision=_decision(),
        failed_jobs=[{"id": 7, "conclusion": "failure"}],
        decision_record_sha256="a" * 64,
    )
    path = tmp_path / "effect-plan.json"
    digest = write_effect_plan(path, plan)

    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["run_id"] = 999
    path.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(EffectPlanError, match="SHA-256 mismatch"):
        read_effect_plan(path, expected_sha256=digest)
