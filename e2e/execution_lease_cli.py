"""CLI helper for durable execution-lease E2E workflows."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from execution_lease import (
    build_contention_resolution_lease,
    build_execution_lease,
    build_takeover_lease,
    lease_digest,
    read_execution_lease,
    write_execution_lease,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _emit(path: str, lease: dict) -> None:
    digest = write_execution_lease(path, lease)
    _write_output("lease-path", path)
    _write_output("lease-sha256", digest)
    _write_output("lease-owner", str(lease["owner_id"]))
    _write_output("lease-epoch", str(lease["epoch"]))
    _write_output("lease-expires-at", str(lease["expires_at"]))
    print(
        f"execution lease owner={lease['owner_id']} epoch={lease['epoch']} "
        f"expires_at={lease['expires_at']} sha256={digest}"
    )


def _wait_until_expired(previous: dict) -> None:
    expiry = datetime.fromisoformat(
        str(previous["expires_at"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    while datetime.now(timezone.utc) < expiry:
        time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    initial = sub.add_parser("initial")
    initial.add_argument("--owner", required=True)
    initial.add_argument("--decision-sha", required=True)
    initial.add_argument("--plan-sha", required=True)
    initial.add_argument("--repository", required=True)
    initial.add_argument("--run-id", required=True, type=int)
    initial.add_argument("--ttl", required=True, type=int)
    initial.add_argument("--output", required=True)

    takeover = sub.add_parser("takeover")
    takeover.add_argument("--previous", required=True)
    takeover.add_argument("--owner", required=True)
    takeover.add_argument("--ttl", required=True, type=int)
    takeover.add_argument("--output", required=True)
    takeover.add_argument("--wait", action="store_true")

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--contender", action="append", required=True)
    resolve.add_argument("--owner", required=True)
    resolve.add_argument("--ttl", required=True, type=int)
    resolve.add_argument("--output", required=True)
    resolve.add_argument("--wait", action="store_true")

    args = parser.parse_args()

    if args.command == "initial":
        lease = build_execution_lease(
            owner_id=args.owner,
            epoch=1,
            decision_record_sha256=args.decision_sha,
            effect_plan_sha256=args.plan_sha,
            repository=args.repository,
            run_id=args.run_id,
            issued_at=_now_iso(),
            ttl_seconds=args.ttl,
        )
        _emit(args.output, lease)
        return 0

    if args.command == "takeover":
        previous = read_execution_lease(args.previous)
        if args.wait:
            _wait_until_expired(previous)
        lease = build_takeover_lease(
            previous_lease=previous,
            owner_id=args.owner,
            issued_at=_now_iso(),
            ttl_seconds=args.ttl,
        )
        _emit(args.output, lease)
        return 0

    contenders = [read_execution_lease(path) for path in args.contender]
    if args.wait:
        for contender in contenders:
            _wait_until_expired(contender)
    lease = build_contention_resolution_lease(
        contending_leases=contenders,
        owner_id=args.owner,
        issued_at=_now_iso(),
        ttl_seconds=args.ttl,
    )
    _emit(args.output, lease)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
