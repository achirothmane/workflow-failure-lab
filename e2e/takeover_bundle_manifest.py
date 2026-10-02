"""Persist and restore deferred-effect bundle metadata across GitHub runners."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


PATH_FIELDS = {
    "decision_record": "DECISION_RECORD_PATH",
    "effect_plan": "EFFECT_PLAN_PATH",
    "eba_request": "EBA_REQUEST_PATH",
    "eba_assumption": "EBA_ASSUMPTION_PATH",
    "eba_authority": "EBA_AUTHORITY_PATH",
    "eba_decision": "EBA_DECISION_PATH",
}

VALUE_FIELDS = {
    "decision_record_sha256": "DECISION_RECORD_SHA256",
    "effect_plan_sha256": "EFFECT_PLAN_SHA256",
    "eba_request_sha256": "EBA_REQUEST_SHA256",
    "eba_assumption_sha256": "EBA_ASSUMPTION_SHA256",
    "eba_authority_sha256": "EBA_AUTHORITY_SHA256",
    "eba_decision_sha256": "EBA_DECISION_SHA256",
    "decision_record_artifact_name": "DECISION_RECORD_ARTIFACT_NAME",
    "decision_experience_json": "DECISION_EXPERIENCE_JSON",
}


def write_manifest(output: Path, bundle_dir: Path) -> None:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    for key, env_name in PATH_FIELDS.items():
        source = Path(os.environ[env_name])
        target = bundle_dir / source.name
        target.write_bytes(source.read_bytes())
        paths[key] = source.name

    values = {key: os.environ[env_name] for key, env_name in VALUE_FIELDS.items()}
    output.write_text(
        json.dumps({"paths": paths, "values": values}, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def export_manifest(manifest: Path, bundle_dir: Path) -> None:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    env_path = os.environ["GITHUB_ENV"]
    with open(env_path, "a", encoding="utf-8") as handle:
        for key, filename in payload["paths"].items():
            handle.write(f"TAKEOVER_{key.upper()}_PATH={bundle_dir / filename}\n")
        for key, value in payload["values"].items():
            env_name = "TAKEOVER_" + key.upper()
            if "\n" in str(value):
                marker = f"EOF_{key.upper()}"
                handle.write(f"{env_name}<<{marker}\n{value}\n{marker}\n")
            else:
                handle.write(f"{env_name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    write = sub.add_parser("write")
    write.add_argument("--output", required=True)
    write.add_argument("--bundle-dir", required=True)

    export = sub.add_parser("export")
    export.add_argument("--manifest", required=True)
    export.add_argument("--bundle-dir", required=True)

    args = parser.parse_args()
    if args.command == "write":
        write_manifest(Path(args.output), Path(args.bundle_dir))
    else:
        export_manifest(Path(args.manifest), Path(args.bundle_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
