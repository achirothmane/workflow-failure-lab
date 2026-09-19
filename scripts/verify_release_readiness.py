from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"release-readiness failure: {message}")


def text(path: str) -> str:
    target = ROOT / path
    require(target.is_file(), f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def input_default(action_text: str, input_name: str) -> str | None:
    pattern = re.compile(
        rf"(?ms)^  {re.escape(input_name)}:\n"
        rf"(.*?)(?=^  [a-zA-Z0-9_-]+:\n|^outputs:|^runs:)"
    )
    match = pattern.search(action_text)
    if not match:
        return None
    default = re.search(r"(?m)^    default:\s*['\"]?([^'\"\n]+)", match.group(1))
    return default.group(1).strip() if default else None


def main() -> int:
    readme = text("README.md")
    action = text("action.yml")
    doctor_action = text("doctor/action.yml")
    text("setup_doctor.py")
    pyproject = text("pyproject.toml")
    text("CHANGELOG.md")
    text("SECURITY.md")
    license_text = text("LICENSE")
    release_doc = text("docs/release-readiness.md")

    require("# CI Retry Gate" in readme, "README product heading is missing")
    require("othy19904-eng/workflow-failure-lab@v1" in readme, "README v1 usage example is missing")
    require("permissions:" in readme and "actions: read" in readme, "README permission guidance is missing")

    require("name: 'CI Retry Gate'" in action, "action.yml product name mismatch")
    description_match = re.search(r"(?m)^description:\s*['\"](.+?)['\"]\s*$", action)
    require(description_match is not None, "action.yml description is missing")
    action_description = description_match.group(1)
    require(len(action_description) < 125, "action.yml description must be less than 125 characters for Marketplace")
    require(license_text.startswith("MIT License"), "LICENSE must be MIT")
    require("using: 'composite'" in action, "action.yml must remain a composite action")
    require("icon: 'shield'" in action, "action branding icon is missing")
    require(input_default(action, "auto-rerun") == "false", "auto-rerun must default to false")
    require(input_default(action, "selective-rerun") == "false", "selective-rerun must default to false")

    require("name: 'CI Retry Gate Setup Doctor'" in doctor_action, "doctor/action.yml product name mismatch")
    require("using: 'composite'" in doctor_action, "Setup Doctor must remain a composite action")
    require(
        input_default(doctor_action, "fail-on-blocked") == "true",
        "Setup Doctor must fail on BLOCKED checks by default",
    )

    require('version = "1.0.1"' in pyproject, "pyproject version must be 1.0.1 for Marketplace patch release")

    # Research-only Causal Dominance must not silently gain production authority.
    production_entrypoints = {
        "ci_retry_gate.py": text("ci_retry_gate.py"),
        "selective_rerun.py": text("selective_rerun.py"),
    }
    forbidden = (
        "causal_dominance_direct_verifier",
        "causal_dominance_shadow",
        "causal_dominance_validation",
        "assess_causal_dominance",
    )
    for path, source in production_entrypoints.items():
        for symbol in forbidden:
            require(symbol not in source, f"{path} imports or uses research-only {symbol}")

    evidence = text("causal_dominance_evidence.py")
    require(
        '("swc-project/swc", 34857087636' in evidence,
        "SWC independent positive control is not pinned",
    )
    require(
        '("pypa/pipx", 31618954128' in evidence,
        "pipx independent positive control is not pinned",
    )
    require(
        "Production promotion for Causal Dominance remains blocked at 2/3" in text("CHANGELOG.md"),
        "release notes must state the Causal Dominance promotion boundary",
    )
    require(
        "Third independent Causal Dominance positive control" in release_doc,
        "release checklist must retain the third-positive evidence item",
    )

    print("release-readiness: PASS")
    print("- v1 metadata present")
    print(f"- Marketplace description length: {len(action_description)} chars")
    print("- MIT license present")
    print("- fail-closed rerun defaults preserved")
    print("- README quick start and permissions present")
    print("- Setup Doctor composite action and fail-closed default present")
    print("- Causal Dominance remains research-only")
    print("- SWC + pipx evidence pinned at 2/3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
