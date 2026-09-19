from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flaky_test_intelligence import FAIL, observations_from_junit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract failing testcase IDs from a JUnit XML report."
    )
    parser.add_argument("junit_path")
    parser.add_argument("--expect-count", type=int)
    args = parser.parse_args()

    xml_text = Path(args.junit_path).read_text(encoding="utf-8")
    observations = observations_from_junit(
        xml_text,
        sha="smoke",
        run_id=1,
        attempt=1,
        job_name="adapter-smoke",
    )
    failed = sorted(
        {item.test_id for item in observations if item.status == FAIL}
    )

    if args.expect_count is not None and len(failed) != args.expect_count:
        raise SystemExit(
            f"expected {args.expect_count} failing testcase(s), found {len(failed)}: {failed}"
        )

    print(json.dumps(failed, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
