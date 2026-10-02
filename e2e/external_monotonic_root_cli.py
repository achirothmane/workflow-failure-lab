"""CLI helper for external monotonic-root E2E workflows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from external_monotonic_root import (
    build_root_record,
    read_root_record,
    root_record_digest,
    write_predicate,
    write_root_record,
)


def _write_output(name: str, value: str) -> None:
    import os

    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--repository", required=True)
    build.add_argument("--run-id", required=True, type=int)
    build.add_argument("--epoch", required=True, type=int)
    build.add_argument("--token", required=True)
    build.add_argument("--decision-sha", required=True)
    build.add_argument("--plan-sha", required=True)
    build.add_argument("--state", required=True, choices=["EXECUTABLE", "CLOSED"])
    build.add_argument("--record", required=True)
    build.add_argument("--predicate", required=True)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--record", required=True)

    args = parser.parse_args()

    if args.command == "build":
        record = build_root_record(
            repository=args.repository,
            run_id=args.run_id,
            epoch=args.epoch,
            fencing_token_sha=args.token,
            decision_record_sha256=args.decision_sha,
            effect_plan_sha256=args.plan_sha,
            lifecycle_state=args.state,
        )
        digest = write_root_record(args.record, record)
        write_predicate(args.predicate, record)

        _write_output("root-record-path", str(Path(args.record)))
        _write_output("root-predicate-path", str(Path(args.predicate)))
        _write_output("root-record-sha256", digest)
        _write_output("root-token-sha", str(record["fencing_token_sha"]))
        _write_output("root-epoch", str(record["epoch"]))
        _write_output("root-state", str(record["lifecycle_state"]))

        print(
            json.dumps(
                {
                    "record": args.record,
                    "predicate": args.predicate,
                    "sha256": digest,
                    "token": record["fencing_token_sha"],
                    "epoch": record["epoch"],
                    "state": record["lifecycle_state"],
                },
                sort_keys=True,
            )
        )
        return 0

    record = read_root_record(args.record)
    print(json.dumps(record, sort_keys=True))
    _write_output("root-record-sha256", root_record_digest(record))
    _write_output("root-token-sha", str(record["fencing_token_sha"]))
    _write_output("root-epoch", str(record["epoch"]))
    _write_output("root-state", str(record["lifecycle_state"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
