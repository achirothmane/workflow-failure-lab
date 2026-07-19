"""B7 release-gate verifier (ADR-0002 gate 7): clean install + CLI smoke.

Proves, without touching the checkout, that:

1. the package installs non-editably into a fresh virtual environment from a
   temporary copy of the packaging inputs (pyproject.toml and src/ only);
2. the installed package resolves inside that environment and outside the
   repository — the temporary source copy is deleted before any verification
   run, so a leaked path or editable-style install fails loudly;
3. the frozen CLI command (ADR-0002: `python -m workflow_failure_lab report
   <path>`) produces the expected incident report from a working directory
   outside the repository, byte-identically across two runs.

Standard library only. Every temporary resource — including child-process
temporary files (TMPDIR/TEMP/TMP) and the pip cache — lives under one
tempfile.TemporaryDirectory and is removed automatically. Exit code 0 on
success with one confirmation line; exit code 1 on the first failed check or
operational error with one precise diagnostic on stderr.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_INPUT = REPO_ROOT / "examples" / "payment-timeout.json"

INSTALL_TIMEOUT_SECONDS = 600
RUN_TIMEOUT_SECONDS = 60

EXPECTED_REPORT_SECTIONS = (
    "## Classification",
    "## Evidence",
    "## Retry Guidance",
    "## Steps",
)


class GateFailure(Exception):
    """One failed gate-7 check, carrying the full diagnostic as its message."""


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


_ENV_REMOVALS = ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
# The complete controlled delta applied to child processes and, during venv
# creation, to os.environ: the three removals above (forced absent) plus the
# five containment settings below (forced set). All eight are saved and
# restored exactly, including prior absence.
_ENV_CONTROLLED = (
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "PYTHONNOUSERSITE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "PIP_CACHE_DIR",
)


def _controlled_env(child_tmp: Path, pip_cache: Path) -> dict[str, str]:
    """Environment for every subprocess: no path leakage into module
    resolution, and every temporary/cache path contained under the gate root.
    """
    env = dict(os.environ)
    for name in _ENV_REMOVALS:
        env.pop(name, None)
    env["PYTHONNOUSERSITE"] = "1"
    for name in ("TMPDIR", "TEMP", "TMP"):
        env[name] = str(child_tmp)
    env["PIP_CACHE_DIR"] = str(pip_cache)
    return env


@contextlib.contextmanager
def _process_env(env: dict[str, str]) -> Iterator[None]:
    """Temporarily apply the complete controlled delta to os.environ.

    venv.EnvBuilder runs in-process and bootstraps pip via an ensurepip child
    that inherits os.environ rather than an explicit env dict, so containment
    must be applied to os.environ for the duration of venv creation: the
    removals become absent (they are missing from env, so they are popped) and
    the containment settings are set. The exact prior state of all eight
    variables — value or absence — is saved first and restored afterwards.
    """
    saved = {name: os.environ.get(name) for name in _ENV_CONTROLLED}
    try:
        for name in _ENV_CONTROLLED:
            if name in env:
                os.environ[name] = env[name]
            else:
                os.environ.pop(name, None)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
    step: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            command, cwd=cwd, env=env, timeout=timeout, capture_output=True
        )
    except subprocess.TimeoutExpired as exc:
        raise GateFailure(f"{step}: timed out after {timeout}s: {command}") from exc


def _check_report_run(step: str, completed: subprocess.CompletedProcess[bytes]) -> None:
    if completed.returncode != 0:
        raise GateFailure(
            f"{step}: expected exit code 0, observed {completed.returncode}\n"
            f"stderr:\n{_text(completed.stderr)}"
        )
    if completed.stderr != b"":
        raise GateFailure(
            f"{step}: expected exactly empty stderr, observed:\n"
            f"{_text(completed.stderr)}"
        )
    stdout = _text(completed.stdout)
    if not stdout.startswith("# Incident Report:"):
        raise GateFailure(
            f"{step}: expected stdout to start with '# Incident Report:', "
            f"observed start: {stdout[:80]!r}"
        )
    for section in EXPECTED_REPORT_SECTIONS:
        if section not in stdout:
            raise GateFailure(
                f"{step}: expected report section {section!r} missing from stdout"
            )
    if "INDETERMINATE" not in stdout:
        raise GateFailure(
            f"{step}: expected classification 'INDETERMINATE' missing from stdout"
        )


def _verify(tmp: Path) -> None:
    if tmp.is_relative_to(REPO_ROOT):
        raise GateFailure(
            f"temporary directory resolved inside the repository: {tmp}"
        )
    child_tmp = tmp / "tmp"
    child_tmp.mkdir()
    pip_cache = tmp / "pip-cache"
    pip_cache.mkdir()
    env = _controlled_env(child_tmp, pip_cache)

    venv_dir = tmp / "venv"
    with _process_env(env):
        venv.EnvBuilder(with_pip=True).create(venv_dir)
    if os.name == "nt":
        python = venv_dir / "Scripts" / "python.exe"
    else:
        python = venv_dir / "bin" / "python"
    python = python.resolve()

    # Packaging inputs only: exactly what pyproject.toml needs to build.
    source_copy = tmp / "srccopy"
    source_copy.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", source_copy / "pyproject.toml")
    shutil.copytree(
        REPO_ROOT / "src",
        source_copy / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )

    install = _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            str(source_copy),
        ],
        cwd=tmp,
        env=env,
        timeout=INSTALL_TIMEOUT_SECONDS,
        step="pip install",
    )
    if install.returncode != 0:
        raise GateFailure(
            f"pip install: expected exit code 0, observed {install.returncode}\n"
            f"stdout:\n{_text(install.stdout)}\nstderr:\n{_text(install.stderr)}"
        )
    # Any editable-style or path-referencing install now breaks loudly.
    shutil.rmtree(source_copy)

    workdir = tmp / "workdir"
    workdir.mkdir()
    shutil.copy2(EXAMPLE_INPUT, workdir / "execution.json")

    probe = _run(
        [
            str(python),
            "-I",
            "-c",
            "import workflow_failure_lab; print(workflow_failure_lab.__file__)",
        ],
        cwd=workdir,
        env=env,
        timeout=RUN_TIMEOUT_SECONDS,
        step="containment probe",
    )
    if probe.returncode != 0:
        raise GateFailure(
            "containment probe: expected exit code 0, observed "
            f"{probe.returncode}\nstderr:\n{_text(probe.stderr)}"
        )
    module_path = Path(_text(probe.stdout).strip()).resolve()
    if not module_path.is_relative_to(venv_dir.resolve()):
        raise GateFailure(
            "containment probe: workflow_failure_lab resolved outside the "
            f"fresh environment {venv_dir}: {module_path}"
        )
    if module_path.is_relative_to(REPO_ROOT):
        raise GateFailure(
            "containment probe: workflow_failure_lab resolved inside the "
            f"repository checkout {REPO_ROOT}: {module_path}"
        )

    report_command = [
        str(python),
        "-I",
        "-m",
        "workflow_failure_lab",
        "report",
        "execution.json",
    ]
    first = _run(
        report_command,
        cwd=workdir,
        env=env,
        timeout=RUN_TIMEOUT_SECONDS,
        step="CLI smoke (run 1)",
    )
    _check_report_run("CLI smoke (run 1)", first)
    second = _run(
        report_command,
        cwd=workdir,
        env=env,
        timeout=RUN_TIMEOUT_SECONDS,
        step="CLI smoke (run 2)",
    )
    _check_report_run("CLI smoke (run 2)", second)
    if second.stdout != first.stdout:
        raise GateFailure(
            "determinism: expected byte-identical stdout across two CLI runs, "
            f"observed {len(first.stdout)} bytes vs {len(second.stdout)} bytes "
            "with differing content"
        )


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="wfl-gate7-") as tmp:
            _verify(Path(tmp).resolve())
    except GateFailure as failure:
        print(f"gate 7 FAILED — {failure}", file=sys.stderr)
        return 1
    except Exception as exc:
        # Operational failure (venv creation, filesystem copy/delete,
        # subprocess startup, cleanup): one concise diagnostic, no traceback.
        # KeyboardInterrupt and SystemExit derive from BaseException and pass
        # through untouched.
        print(f"gate 7 FAILED — {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "gate 7 OK: clean-package install and CLI smoke verified "
        "in a fresh environment"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
