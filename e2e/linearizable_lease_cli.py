"""CLI helper for Git-ref backed lease acquisition E2E."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ci_retry_gate import GitHubAPI
from linearizable_lease import (
    build_candidate_commit,
    build_tombstone_commit,
    create_coordination_ref,
    delete_coordination_ref,
    publish_candidate,
    read_coordination_sha,
    try_claim,
)


def _api() -> GitHubAPI:
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    return GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed")
    seed.add_argument("--base-sha", required=True)

    claim = sub.add_parser("claim")
    claim.add_argument("--base-sha", required=True)
    claim.add_argument("--owner", required=True)
    claim.add_argument("--epoch", required=True, type=int)
    claim.add_argument("--decision-sha", required=True)
    claim.add_argument("--plan-sha", required=True)
    claim.add_argument("--result", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--base-sha", required=True)
    prepare.add_argument("--owner", required=True)
    prepare.add_argument("--epoch", required=True, type=int)
    prepare.add_argument("--decision-sha", required=True)
    prepare.add_argument("--plan-sha", required=True)
    prepare.add_argument("--result", required=True)

    publish = sub.add_parser("publish")
    publish.add_argument("--base-sha", required=True)
    publish.add_argument("--owner", required=True)
    publish.add_argument("--candidate-sha", required=True)
    publish.add_argument("--result", required=True)

    tombstone = sub.add_parser("prepare-tombstone")
    tombstone.add_argument("--base-sha", required=True)
    tombstone.add_argument("--decision-sha", required=True)
    tombstone.add_argument("--plan-sha", required=True)
    tombstone.add_argument("--reason", required=True)
    tombstone.add_argument("--result", required=True)

    sub.add_parser("read")
    sub.add_parser("delete")

    args = parser.parse_args()
    api = _api()

    if args.command == "seed":
        observed = create_coordination_ref(
            api,
            args.repository,
            args.ref,
            args.base_sha,
        )
        _write_output("coordination-sha", observed)
        print(f"coordination ref seeded at {observed}")
        return 0

    if args.command == "read":
        observed = read_coordination_sha(api, args.repository, args.ref)
        _write_output("coordination-sha", observed)
        print(observed)
        return 0

    if args.command == "delete":
        delete_coordination_ref(api, args.repository, args.ref)
        print("coordination ref deleted")
        return 0

    if args.command == "prepare-tombstone":
        candidate_sha = build_tombstone_commit(
            api,
            args.repository,
            base_sha=args.base_sha,
            decision_record_sha256=args.decision_sha,
            effect_plan_sha256=args.plan_sha,
            reason=args.reason,
        )
        prepared = {
            "coordination_ref": args.ref,
            "base_sha": args.base_sha,
            "candidate_sha": candidate_sha,
            "kind": "closed",
        }
        path = Path(args.result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(prepared, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_output("candidate-sha", candidate_sha)
        _write_output("base-sha", args.base_sha)
        print(json.dumps(prepared, sort_keys=True))
        return 0

    if args.command == "prepare":
        candidate_sha = build_candidate_commit(
            api,
            args.repository,
            base_sha=args.base_sha,
            owner_id=args.owner,
            epoch=args.epoch,
            decision_record_sha256=args.decision_sha,
            effect_plan_sha256=args.plan_sha,
        )
        prepared = {
            "owner_id": args.owner,
            "coordination_ref": args.ref,
            "base_sha": args.base_sha,
            "candidate_sha": candidate_sha,
            "epoch": args.epoch,
        }
        path = Path(args.result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(prepared, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_output("owner", args.owner)
        _write_output("candidate-sha", candidate_sha)
        _write_output("base-sha", args.base_sha)
        print(json.dumps(prepared, sort_keys=True))
        return 0

    if args.command == "publish":
        result = publish_candidate(
            api,
            args.repository,
            coordination_ref=args.ref,
            expected_base_sha=args.base_sha,
            owner_id=args.owner,
            candidate_sha=args.candidate_sha,
        )
        path = Path(args.result)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.as_dict(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_output("acquired", "true" if result.acquired else "false")
        _write_output("owner", result.owner_id)
        _write_output("candidate-sha", result.candidate_sha)
        _write_output("observed-sha", result.observed_sha)
        _write_output("reason", result.reason)
        print(json.dumps(result.as_dict(), sort_keys=True))
        return 0

    result = try_claim(
        api,
        args.repository,
        coordination_ref=args.ref,
        expected_base_sha=args.base_sha,
        owner_id=args.owner,
        epoch=args.epoch,
        decision_record_sha256=args.decision_sha,
        effect_plan_sha256=args.plan_sha,
    )
    path = Path(args.result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.as_dict(), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    _write_output("acquired", "true" if result.acquired else "false")
    _write_output("owner", result.owner_id)
    _write_output("candidate-sha", result.candidate_sha)
    _write_output("observed-sha", result.observed_sha)
    _write_output("reason", result.reason)
    print(json.dumps(result.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
