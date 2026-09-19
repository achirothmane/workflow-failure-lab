from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: extract_junit_id.py <junit.xml>")

    root = ET.fromstring(Path(sys.argv[1]).read_text(encoding="utf-8"))
    failed: list[str] = []
    for case in root.iter():
        if local_name(case.tag) != "testcase":
            continue
        if not any(local_name(child.tag) in {"failure", "error"} for child in list(case)):
            continue
        classname = str(case.attrib.get("classname") or "").strip()
        name = str(case.attrib.get("name") or "").strip()
        test_id = f"{classname}::{name}" if classname else name
        if test_id:
            failed.append(test_id)

    unique = sorted(set(failed))
    if len(unique) != 1:
        raise SystemExit(f"expected exactly one failed testcase, found {unique}")

    print(json.dumps(unique, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
