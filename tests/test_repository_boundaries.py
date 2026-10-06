"""Repository-boundary tests for product, research, and validation layers.

The product runtime may be exercised by research and validation code, but the
dependency direction must not point back from product runtime into those
internal support layers.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PREFIXES = ("research", "validation")


def _python_product_files() -> tuple[Path, ...]:
    root_modules = tuple(sorted(ROOT.glob("*.py")))
    package_modules = tuple(sorted((ROOT / "src").rglob("*.py")))
    runtime_modules = tuple(sorted((ROOT / "runtime").rglob("*.py")))
    return root_modules + package_modules + runtime_modules


def _forbidden_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_PREFIXES:
                    imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] in FORBIDDEN_PREFIXES:
                imports.add(node.module)

    return tuple(sorted(imports))


def test_product_runtime_does_not_import_research_or_validation() -> None:
    violations = []
    for path in _python_product_files():
        for imported in _forbidden_imports(path):
            violations.append(f"{path.relative_to(ROOT)} -> {imported}")

    assert not violations, (
        "product runtime must not depend on internal research/validation layers:\n"
        + "\n".join(violations)
    )


def test_boundary_guard_covers_root_and_packaged_product_code() -> None:
    files = {path.relative_to(ROOT).as_posix() for path in _python_product_files()}
    assert "ci_retry_gate.py" in files
    assert "benchmark_mode.py" in files
    assert "flaky_test_history.py" in files
    assert "src/workflow_failure_lab/__main__.py" in files
    assert "runtime/benchmark/classifier_rule_research.py" in files
    assert "runtime/flaky/historical_flakiness_evidence.py" in files
    assert "runtime/flaky/flaky_test_intelligence.py" in files
