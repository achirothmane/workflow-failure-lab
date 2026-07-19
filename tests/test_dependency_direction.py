"""B5 dependency-direction tests: enforce implementation plan §3.

The module dependency direction and the no-cycles rule are stated in
docs/implementation-plan.md §3 and deferred there to a test ("enforced by a
test in B-later"). The import graph is built from the Python AST of every
top-level module in the package — no source-text matching, nothing imported
or executed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_NAME = "workflow_failure_lab"
PACKAGE_DIR = Path(__file__).resolve().parent.parent / "src" / PACKAGE_NAME

# Approved B5 rule table (implementation plan §3). __main__ is the only row
# containing "parsing": no module imports parsing except the CLI entry point.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "__init__": frozenset(),
    "__main__": frozenset({
        "analysis",
        "parsing",
        "reporting",
        "retry_policy",
    }),
    "domain": frozenset(),
    "parsing": frozenset({"domain"}),
    "analysis": frozenset({"domain"}),
    "retry_policy": frozenset({"domain"}),
    "reporting": frozenset({"domain", "analysis", "retry_policy"}),
}


def _discover_modules() -> tuple[str, ...]:
    """Every top-level module in the package, in deterministic order."""
    return tuple(sorted(path.stem for path in PACKAGE_DIR.glob("*.py")))


def _internal_imports(path: Path, module_names: frozenset[str]) -> tuple[str, ...]:
    """Package-internal modules imported by one file, from its AST.

    Covers absolute imports (import workflow_failure_lab.x), from-package
    imports (from workflow_failure_lab.x import y / from workflow_failure_lab
    import x), and relative imports (from . import x / from .x import y).
    Imports of anything outside the package are ignored.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] != PACKAGE_NAME:
                    continue
                targets.add(parts[1] if len(parts) > 1 else "__init__")
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                # Relative: the package has no subpackages, so any level
                # resolves inside it.
                if node.module is None:
                    targets.update(
                        alias.name for alias in node.names if alias.name in module_names
                    )
                else:
                    targets.add(node.module.split(".")[0])
            elif node.module is not None:
                parts = node.module.split(".")
                if parts[0] != PACKAGE_NAME:
                    continue
                if len(parts) > 1:
                    targets.add(parts[1])
                else:
                    targets.update(
                        alias.name for alias in node.names if alias.name in module_names
                    )
    return tuple(sorted(targets))


def _import_graph() -> dict[str, tuple[str, ...]]:
    modules = _discover_modules()
    names = frozenset(modules)
    return {
        module: _internal_imports(PACKAGE_DIR / f"{module}.py", names)
        for module in modules
    }


def test_every_package_module_has_a_dependency_rule() -> None:
    """The rule table is total: no module can bypass B5 by being unlisted."""
    discovered = set(_discover_modules())
    expected = set(ALLOWED_IMPORTS)
    missing_rules = sorted(discovered - expected)
    missing_modules = sorted(expected - discovered)
    assert discovered == expected, (
        f"modules without a dependency rule: {missing_rules}; "
        f"rules without a module on disk: {missing_modules}"
    )


def test_imports_respect_documented_dependency_direction(tmp_path: Path) -> None:
    # Detector sanity check: the package-root import must map to __init__,
    # the dotted import to its submodule, and external imports to nothing.
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json\n"
        "import workflow_failure_lab\n"
        "import workflow_failure_lab.analysis\n",
        encoding="utf-8",
    )
    assert _internal_imports(probe, frozenset(_discover_modules())) == (
        "__init__",
        "analysis",
    )

    violations = [
        f"{module} -> {target}"
        for module, targets in _import_graph().items()
        for target in targets
        if target not in ALLOWED_IMPORTS.get(module, frozenset())
    ]
    assert not violations, (
        "import edges not permitted by implementation plan §3:\n"
        + "\n".join(violations)
    )


def test_import_graph_has_no_cycles() -> None:
    """Independent of the rule table: checks the actual graph for cycles."""
    graph = _import_graph()
    color = {module: "white" for module in graph}
    for root in graph:
        if color[root] != "white":
            continue
        path = [root]
        color[root] = "gray"
        stack = [iter(graph[root])]
        while stack:
            target = next(stack[-1], None)
            if target is None:
                color[path.pop()] = "black"
                stack.pop()
                continue
            if target not in color:
                continue
            if color[target] == "gray":
                cycle = path[path.index(target) :] + [target]
                pytest.fail("import cycle: " + " -> ".join(cycle))
            if color[target] == "white":
                color[target] = "gray"
                path.append(target)
                stack.append(iter(graph[target]))
