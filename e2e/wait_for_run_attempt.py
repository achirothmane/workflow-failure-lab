"""Wait until a target GitHub Actions run reaches a requested attempt."""

from __future__ import annotations

import json
import os
import time
import urllib.request


def main() -> int:
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    repo = os.environ["TARGET_REPOSITORY"]
    run_id = int(os.environ["TARGET_RUN_ID"])
    target_attempt = int(os.environ.get("TARGET_ATTEMPT", "2"))
    token = os.environ["GITHUB_TOKEN"]
    timeout_seconds = int(os.environ.get("WAIT_TIMEOUT_SECONDS", "60"))
    url = f"{api}/repos/{repo}/actions/runs/{run_id}"

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)

        observed = int(payload.get("run_attempt") or 0)
        if observed >= target_attempt:
            print(f"target advanced to attempt {observed}")
            return 0
        time.sleep(1)

    print(
        f"target did not reach attempt {target_attempt} within {timeout_seconds}s",
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
