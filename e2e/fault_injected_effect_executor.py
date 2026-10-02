"""Fault-injection wrapper for live crash-window E2E only.

This script never changes production effect semantics. It monkeypatches the GitHub
dispatch method inside a dedicated test process so the live workflows can exercise
crash/transport windows around the real effect boundary.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import effect_executor


def main() -> int:
    mode = str(os.environ.get("FAULT_MODE") or "").strip()
    original = effect_executor.GitHubAPI.rerun_failed_jobs

    if mode == "crash-before-dispatch":
        def crash_before(self, repo: str, run_id: int):
            print("fault-injection: crash before rerun dispatch", flush=True)
            os._exit(86)

        effect_executor.GitHubAPI.rerun_failed_jobs = crash_before

    elif mode == "crash-after-dispatch":
        def crash_after(self, repo: str, run_id: int):
            original(self, repo, run_id)
            print("fault-injection: crash after accepted rerun dispatch", flush=True)
            os._exit(87)

        effect_executor.GitHubAPI.rerun_failed_jobs = crash_after

    elif mode == "timeout-after-dispatch":
        def timeout_after(self, repo: str, run_id: int):
            original(self, repo, run_id)
            raise RuntimeError(
                "synthetic transport timeout after dispatch; acceptance is intentionally ambiguous"
            )

        effect_executor.GitHubAPI.rerun_failed_jobs = timeout_after

    else:
        raise SystemExit(f"unsupported FAULT_MODE={mode!r}")

    return effect_executor.main()


if __name__ == "__main__":
    raise SystemExit(main())
