from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from execution_lease import (
    ExecutionLeaseError,
    build_contention_resolution_lease,
    build_execution_lease,
    build_takeover_lease,
    current_registry_lease,
    lease_digest,
    verify_effect_ownership,
)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _initial(now: datetime):
    return build_execution_lease(
        owner_id="worker-a",
        epoch=1,
        decision_record_sha256="a" * 64,
        effect_plan_sha256="b" * 64,
        repository="owner/repo",
        run_id=123,
        issued_at=_iso(now),
        ttl_seconds=10,
    )


def test_takeover_requires_previous_lease_expiry():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)

    with pytest.raises(ExecutionLeaseError, match="LEASE_STILL_ACTIVE"):
        build_takeover_lease(
            previous_lease=first,
            owner_id="worker-b",
            issued_at=_iso(now + timedelta(seconds=9)),
            ttl_seconds=30,
        )

    second = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-b",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=30,
    )
    assert second["epoch"] == 2
    assert second["owner_id"] == "worker-b"
    assert second["previous_lease_sha256"] == lease_digest(first)


def test_old_owner_is_fenced_after_takeover_even_if_subject_state_is_unchanged():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)
    second = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-b",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=30,
    )
    registry = [first, second]

    with pytest.raises(ExecutionLeaseError, match="LEASE_SUPERSEDED"):
        verify_effect_ownership(
            candidate_lease=first,
            registry_leases=registry,
            expected_owner_id="worker-a",
            decision_record_sha256="a" * 64,
            effect_plan_sha256="b" * 64,
            repository="owner/repo",
            run_id=123,
            now=_iso(now + timedelta(seconds=11)),
        )

    verify_effect_ownership(
        candidate_lease=second,
        registry_leases=registry,
        expected_owner_id="worker-b",
        decision_record_sha256="a" * 64,
        effect_plan_sha256="b" * 64,
        repository="owner/repo",
        run_id=123,
        now=_iso(now + timedelta(seconds=11)),
    )


def test_same_epoch_split_brain_fails_closed():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)
    competing = build_execution_lease(
        owner_id="worker-x",
        epoch=1,
        decision_record_sha256="a" * 64,
        effect_plan_sha256="b" * 64,
        repository="owner/repo",
        run_id=123,
        issued_at=_iso(now),
        ttl_seconds=10,
    )

    with pytest.raises(ExecutionLeaseError, match="LEASE_EPOCH_CONFLICT"):
        current_registry_lease([first, competing])


def test_expired_current_owner_cannot_execute_without_takeover():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)

    with pytest.raises(ExecutionLeaseError, match="LEASE_EXPIRED"):
        verify_effect_ownership(
            candidate_lease=first,
            registry_leases=[first],
            expected_owner_id="worker-a",
            decision_record_sha256="a" * 64,
            effect_plan_sha256="b" * 64,
            repository="owner/repo",
            run_id=123,
            now=_iso(now + timedelta(seconds=10)),
        )



def test_contention_resolution_waits_for_all_competing_epochs_to_expire():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)
    b = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-b",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=20,
    )
    c_lease = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-c",
        issued_at=_iso(now + timedelta(seconds=11)),
        ttl_seconds=25,
    )

    with pytest.raises(ExecutionLeaseError, match="LEASE_CONTENTION_ACTIVE"):
        build_contention_resolution_lease(
            contending_leases=[b, c_lease],
            owner_id="resolver-d",
            issued_at=_iso(now + timedelta(seconds=35)),
            ttl_seconds=30,
        )

    resolved = build_contention_resolution_lease(
        contending_leases=[b, c_lease],
        owner_id="resolver-d",
        issued_at=_iso(now + timedelta(seconds=36)),
        ttl_seconds=30,
    )
    assert resolved["epoch"] == 3
    assert resolved["owner_id"] == "resolver-d"
    assert resolved["previous_lease_sha256"] is None
    assert resolved["previous_lease_set_sha256"]


def test_resolved_epoch_fences_all_same_epoch_contenders():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)
    b = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-b",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=20,
    )
    c_lease = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-c",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=20,
    )

    with pytest.raises(ExecutionLeaseError, match="LEASE_EPOCH_CONFLICT"):
        verify_effect_ownership(
            candidate_lease=b,
            registry_leases=[first, b, c_lease],
            expected_owner_id="worker-b",
            decision_record_sha256="a" * 64,
            effect_plan_sha256="b" * 64,
            repository="owner/repo",
            run_id=123,
            now=_iso(now + timedelta(seconds=11)),
        )

    resolved = build_contention_resolution_lease(
        contending_leases=[b, c_lease],
        owner_id="resolver-d",
        issued_at=_iso(now + timedelta(seconds=30)),
        ttl_seconds=30,
    )
    registry = [first, b, c_lease, resolved]

    for contender, owner in ((b, "worker-b"), (c_lease, "worker-c")):
        with pytest.raises(ExecutionLeaseError, match="LEASE_SUPERSEDED"):
            verify_effect_ownership(
                candidate_lease=contender,
                registry_leases=registry,
                expected_owner_id=owner,
                decision_record_sha256="a" * 64,
                effect_plan_sha256="b" * 64,
                repository="owner/repo",
                run_id=123,
                now=_iso(now + timedelta(seconds=31)),
            )

    verify_effect_ownership(
        candidate_lease=resolved,
        registry_leases=registry,
        expected_owner_id="resolver-d",
        decision_record_sha256="a" * 64,
        effect_plan_sha256="b" * 64,
        repository="owner/repo",
        run_id=123,
        now=_iso(now + timedelta(seconds=31)),
    )


def test_contention_resolution_rejects_mixed_effect_bindings():
    now = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    first = _initial(now)
    b = build_takeover_lease(
        previous_lease=first,
        owner_id="worker-b",
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=10,
    )
    other = build_execution_lease(
        owner_id="worker-c",
        epoch=2,
        decision_record_sha256="c" * 64,
        effect_plan_sha256="d" * 64,
        repository="owner/repo",
        run_id=123,
        issued_at=_iso(now + timedelta(seconds=10)),
        ttl_seconds=10,
    )

    with pytest.raises(ExecutionLeaseError, match="LEASE_CONTENTION_BINDING_MISMATCH"):
        build_contention_resolution_lease(
            contending_leases=[b, other],
            owner_id="resolver-d",
            issued_at=_iso(now + timedelta(seconds=20)),
            ttl_seconds=30,
        )
