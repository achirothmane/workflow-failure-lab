"""Run the CI retry gate as a separate process over an EvidenceBundle artifact."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from evidence_artifact import EvidenceArtifactError, read_evidence_artifact
from evidence_gate import build_ci_retry_decision


def _blocked_artifact_error(reason: str, max_attempts: int) -> dict[str, Any]:
    return {
        "schema_version": "ci-retry-gate.evidence-decision.v1",
        "action": "rerun_ci",
        "decision": "BLOCK",
        "evidence_status": "UNKNOWN",
        "confidence": "unknown",
        "observed_at": None,
        "fresh_until": None,
        "freshness_basis": "Evidence artifact verification failed; no action is authorized.",
        "scope": {
            "repository": "",
            "run_id": None,
            "run_attempt": None,
            "head_sha": "",
            "workflow_id": None,
        },
        "policy": {"max_attempts": max_attempts},
        "evidence_bundle": None,
        "reasons": [reason],
        "contradictions": [],
        "failed_jobs": [],
        "rerun_triggered": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--max-attempts", required=True, type=int)
    args = parser.parse_args(argv)

    try:
        bundle = read_evidence_artifact(
            args.evidence,
            expected_sha256=args.expected_sha256,
        )
        decision = build_ci_retry_decision(
            bundle,
            max_attempts=args.max_attempts,
        )
    except EvidenceArtifactError as exc:
        decision = _blocked_artifact_error(
            f"Evidence artifact verification failed: {exc}",
            args.max_attempts,
        )
    except Exception as exc:
        # The runtime boundary is fail-closed: an unexpected gate failure can
        # never become implicit authorization.
        decision = _blocked_artifact_error(
            f"Evidence gate failed closed: {type(exc).__name__}: {exc}",
            args.max_attempts,
        )

    sys.stdout.write(json.dumps(decision, sort_keys=True, separators=(",", ":")))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
