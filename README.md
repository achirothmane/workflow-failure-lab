# CI Retry Gate

CI Retry Gate is a GitHub Action that inspects failed GitHub Actions jobs, decides whether an automatic rerun is safe, and analyzes recent workflow history for recurring failures and CI waste.

It is deliberately conservative: a rerun is allowed only when **every failed job** looks like a high-confidence transient infrastructure/network failure and no deploy, publish, migration, release, or other side-effect signal is detected.

## Why

Blindly rerunning failed CI can hide flaky infrastructure, waste runner minutes, or repeat a destructive step. CI Retry Gate adds a safety decision before any rerun and now also shows whether the same failures keep returning over recent runs.

The action currently classifies failures into:

- `RUNNER_INFRA`
- `DEPENDENCY_NETWORK`
- `RESOURCE_TIMEOUT`
- `FLAKY_TEST`
- `CODE_REGRESSION`
- `UNKNOWN`

Automatic rerun is disabled by default.

## CI History & Waste

For the same workflow, the action can inspect recent completed runs and report:

- total runtime spent in failed jobs;
- high-confidence transient failure runtime, treated as a CI-waste signal;
- recurring job/category failure patterns seen at least twice;
- the number of historical runs actually analyzed.

This distinction is intentional: **failed runtime is not automatically waste**. A real code regression can be useful CI work. The `historical-transient-waste-minutes` metric counts only failures classified with high confidence as runner/infrastructure or dependency/network failures.

The default history window is 10 previous completed runs and can be increased up to 50.

## Basic usage

Run the gate after your main CI workflow completes:

```yaml
name: CI Retry Gate

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

permissions:
  actions: read
  contents: read

jobs:
  gate:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - uses: othy19904-eng/workflow-failure-lab@v1
        with:
          github-token: ${{ github.token }}
          auto-rerun: 'false'
          history-runs: '10'
          comment-on-pr: 'false'
```

With automatic rerun enabled:

```yaml
permissions:
  actions: write
  contents: read

jobs:
  gate:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - uses: othy19904-eng/workflow-failure-lab@v1
        with:
          github-token: ${{ github.token }}
          auto-rerun: 'true'
          max-attempts: '2'
          history-runs: '20'
          comment-on-pr: 'false'
```

To also post the current-run gate report on an associated pull request, give the token either `pull-requests: write` or `issues: write` and set `comment-on-pr: 'true'`.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `github-token` | required | Reads workflow runs/logs; needs Actions write only when rerunning. |
| `run-id` | workflow-run event ID | Workflow run to inspect. |
| `repository` | current repository | Repository in `owner/name` form. |
| `auto-rerun` | `false` | Actually rerun failed jobs when the safety gate passes. |
| `max-attempts` | `2` | Prevents rerun loops. |
| `comment-on-pr` | `true` | Posts the current-run Markdown report to the associated PR when permitted. |
| `history-runs` | `10` | Previous completed runs of the same workflow to inspect; capped at 50. |

## Outputs

| Output | Meaning |
|---|---|
| `safe-to-rerun` | `true` only when every failed job is a high-confidence transient failure and no side-effect signal is found. |
| `rerun-triggered` | Whether this invocation actually requested a rerun. |
| `failed-jobs` | Number of failed jobs assessed in the current run. |
| `wasted-minutes` | Observed runtime across failed jobs in the current run. |
| `history-runs-analyzed` | Number of previous completed runs actually inspected. |
| `historical-failed-minutes` | Runtime across failed jobs in the sampled history; not all of this is necessarily waste. |
| `historical-transient-waste-minutes` | Historical runtime from high-confidence runner/infrastructure or dependency/network failures. |
| `recurring-failures` | Number of recurring job/category failure patterns seen at least twice. |

## Safety model

The action fails closed. `UNKNOWN`, code failures, mixed evidence, low-confidence classifications, and side-effect signals all block automatic rerun. Log evidence is redacted for common token/API-key patterns before it is included in reports.

History analysis is read-only. It reads previous workflow runs, jobs, and logs through the GitHub API and does not persist them to an external database.

This tool cannot prove that rerunning arbitrary third-party workflows is safe. Its output is a conservative heuristic based on available GitHub job metadata and logs; keep `auto-rerun: false` while evaluating it on your repositories.

## Validation

The action has unit coverage for transient failures, code failures, unknown failures, secret redaction, side-effect blocking, attempt caps, runtime accounting, historical transient-waste accounting, recurring failure detection, and empty history.

An end-to-end GitHub Actions fixture was also run against the action: an intentionally failed network-style job was detected as safe to rerun, while the gate itself remained read-only and did not trigger a rerun.

---

## Workflow Failure Lab CLI

This repository also contains the earlier deterministic local CLI used to analyze workflow execution evidence.

The CLI classifies an execution with exactly one of three terms:

| Term | Meaning |
|---|---|
| `SUCCEEDED` | The execution completed with enough evidence of success. |
| `FAILED_CONFIRMED` | The execution failed and the failure is confirmed. |
| `INDETERMINATE` | The available data cannot prove success or confirmed failure. |

### Install

Requires Python 3.12+.

```bash
pip install -e ".[test]"
```

### CLI usage

```bash
python -m workflow_failure_lab report examples/payment-timeout.json
```

### Tests

```bash
pytest
```

CI runs the test suite on Python 3.12 and also performs a clean-install verification gate.
