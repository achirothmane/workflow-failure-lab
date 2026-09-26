from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_orchestrator_does_not_import_authorization_gate() -> None:
    imports = _imports(ROOT / "ci_retry_gate.py")

    assert "evidence_gate" not in imports


def test_gate_cli_is_the_runtime_authorization_entrypoint() -> None:
    orchestrator = (ROOT / "ci_retry_gate.py").read_text(encoding="utf-8")

    assert "evidence_gate_cli.py" in orchestrator
    assert "write_evidence_artifact" in orchestrator
    assert "subprocess.run" in orchestrator
