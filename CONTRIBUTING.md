# Contributing to CI Retry Gate

Thanks for helping improve CI Retry Gate.

The project is intentionally conservative: changes should make retry decisions easier to trust, easier to adopt, or easier to verify without weakening the fail-closed behavior.

## Start locally

Requirements:

- Python 3.12+
- Git

Install the project and test dependencies:

```bash
make install
```

Run the test suite:

```bash
make test
```

Verify the clean-install path used by release checks:

```bash
make verify-clean-install
```

A small packaged CLI demo is also available:

```bash
make demo
```

## Repository boundaries

The repository has explicit layers:

- root entry points such as `ci_retry_gate.py`, `benchmark_mode.py`, and `flaky_test_history.py` remain visible when Actions or adapters invoke them directly;
- `runtime/` contains internal product runtime support;
- `research/` contains falsification and hypothesis work;
- `validation/` contains release and regression validation assets;
- `src/workflow_failure_lab/` contains the packaged CLI/library surface.

Dependency direction is enforced by CI: product runtime must not import `research/` or `validation/`.

Do not move a module based on its name alone. First confirm whether it participates in a stable Action, adapter, Doctor, or benchmark execution path.

## Stable product contract

Treat these as release-sensitive surfaces:

- `action.yml` inputs and outputs;
- the stable `@v1` behavior;
- the Setup Doctor contract;
- pytest/Jest/Vitest adapter contracts;
- documented machine-readable outputs.

If a change affects one of those surfaces, call it out explicitly in the pull request and update the relevant documentation and compatibility tests.

## Safety expectations

Changes must preserve the conservative default behavior:

- no automatic rerun without explicit opt-in;
- missing or contradictory evidence must not silently become permission;
- side-effect risk remains an independent blocker;
- research or benchmark evidence must not silently change production authority;
- tests should cover both the intended path and the failure boundary.

Do not include tokens, secrets, private CI logs, or credentials in fixtures, issues, or pull requests.

## Pull requests

Keep structural changes bounded. Prefer one clear architectural move per pull request so CI can prove the boundary before the next move.

Before opening a pull request:

1. run `make test`;
2. run `make verify-clean-install` when packaging or imports changed;
3. update docs when the public or architectural contract changed;
4. explain whether `action.yml`, `@v1`, adapters, retry authority, or write behavior changed.

The pull-request template mirrors these checks.

## Bug reports and feature requests

Use the GitHub issue templates for product bugs and feature requests.

For a public failed workflow that you want CI Retry Gate to analyze, use the dedicated **Should I retry this failed GitHub Action?** template instead of filing a bug.

For security vulnerabilities, follow [SECURITY.md](SECURITY.md). Do not disclose sensitive exploit details in a public issue.
