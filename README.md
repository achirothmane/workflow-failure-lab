# CI Retry Gate

CI Retry Gate is a GitHub Action that inspects failed GitHub Actions jobs, decides whether a rerun is safe, can selectively rerun only safe transient jobs, fingerprints recurring failures, learns conservative retry-policy recommendations from real rerun history, shadow-tests those policies, benchmarks them across repositories, and surfaces CI waste.

It is deliberately conservative: code regressions, unknown or low-confidence failures, attempt caps, and deploy/publish/migration/release side-effect signals stay blocked.

## Why

Blindly rerunning failed CI can hide flaky infrastructure, waste runner minutes, or repeat destructive steps. CI Retry Gate adds a safety decision before any rerun and shows whether the same underlying failure keeps returning over time.

The action currently classifies failures into:

- `RUNNER_INFRA`
- `DEPENDENCY_NETWORK`
- `RESOURCE_TIMEOUT`
- `FLAKY_TEST`
- `CODE_REGRESSION`
- `UNKNOWN`

Automatic rerun is disabled by default.

## Failure fingerprints + CI History & Waste

For the same workflow, the action can inspect recent completed runs and report:

- deterministic fingerprints for normalized failure signatures;
- exact fingerprints that recur across runs or attempts;
- whether a failed job was actually rerun and whether that rerun recovered;
- total runtime spent in failed jobs;
- high-confidence transient failure runtime, treated as a CI-waste signal;
- broader recurring job/category patterns.

A fingerprint is derived from the job name, failure category, and normalized evidence lines. Dynamic values such as timestamps, IP addresses, long hex IDs, and standalone numbers are normalized before hashing, so the same underlying failure does not become a new fingerprint just because an IP, request ID, or timestamp changed.

Example:

```text
FG-4A92F6D13C21
install dependencies · DEPENDENCY_NETWORK
8 occurrences · 5 real reruns · 4 recoveries · 31.20 failed minutes
```

This distinction is intentional: **failed runtime is not automatically waste**. A real code regression can be useful CI work. `historical-transient-waste-minutes` counts only failures classified with high confidence as runner/infrastructure or dependency/network failures.

The default history window is 10 previous completed runs and can be increased up to 50.

## Policy Learning

Policy Learning turns fingerprint history into a conservative recommendation for each fingerprint:

- `AUTO_RERUN_ONCE`
- `MANUAL_REVIEW`
- `DO_NOT_AUTO_RERUN`

`AUTO_RERUN_ONCE` is recommended only when all of the following are true:

- the fingerprint belongs to `RUNNER_INFRA` or `DEPENDENCY_NETWORK`;
- at least 5 **real** reruns were observed;
- at least 80% of those reruns recovered;
- at least 80% of the fingerprint occurrences were classified with high confidence;
- no side-effect signal was observed.

Policy Learning is advisory only. It does not silently change the selective-rerun safety gate or enable reruns by itself.

GitHub can copy an untouched job into a later workflow attempt when another job is rerun. CI Retry Gate therefore counts a rerun sample only when the same job has a genuinely different `started_at` time in a later attempt. This avoids learning policies from copied historical records.

## Policy Shadow Mode

`policy-shadow-mode: 'true'` runs a read-only retrospective backtest. For each historical point it uses only evidence older than that point, then checks whether a real later rerun recovered. Outcomes without an observed rerun remain `UNKNOWN` rather than being guessed.

Shadow Mode reports decisions, evaluated decisions, recoveries, false positives, unknown outcomes, observed precision, and the failed-job runtime represented by observed recoveries. It never triggers a rerun.

## Benchmark Mode

`benchmark-mode: 'true'` extends the same shadow backtest across a list of repositories. It is read-only and keeps Policy Learning **repository-local**: evidence from repository A cannot promote a fingerprint in repository B.

Benchmark Mode samples completed workflow runs, reads first-attempt failed jobs, detects real later attempts of the same job, and reports:

- repositories and completed runs analyzed;
- first-attempt failed jobs;
- shadow `AUTO_RERUN_ONCE` decisions;
- evaluated decisions with a real rerun outcome;
- recoveries, false positives, and unknown outcomes;
- observed precision;
- decision coverage and evaluated coverage;
- results broken down by failure category and repository.

Example:

```yaml
- uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    benchmark-mode: 'true'
    benchmark-repositories: |
      owner/project-one
      owner/project-two
      another/project
    benchmark-runs: '20'
    auto-rerun: 'false'
    selective-rerun: 'false'
    comment-on-pr: 'false'
```

The repository list is capped at 50 and `benchmark-runs` is capped at 50 per repository. Public or otherwise token-accessible repositories can be analyzed; inaccessible repositories are reported as skipped instead of aborting the whole benchmark.

**Observed precision is not overall classifier accuracy.** It is `recoveries / evaluated AUTO_RERUN_ONCE shadow decisions`. Unknown counterfactual outcomes are excluded rather than counted as successes or failures. Benchmark results describe only the sampled history and are not a guarantee of future behavior.

## Selective Safe Rerun

`selective-rerun: 'true'` reruns only failed jobs that are high-confidence transient failures. Code regressions, unknown failures, low-confidence failures, and side-effect jobs remain blocked. The attempt cap prevents rerun loops.

Because GitHub may also rerun dependent jobs when one job is rerun, selective mode fails closed if the workflow contains deploy/publish/migrate or other side-effect signals.

## Basic usage

Read-only evaluation:

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
          selective-rerun: 'false'
          history-runs: '10'
          comment-on-pr: 'false'
```

Selective safe rerun:

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
          auto-rerun: 'false'
          selective-rerun: 'true'
          max-attempts: '2'
          history-runs: '20'
          comment-on-pr: 'false'
```

`auto-rerun` and `selective-rerun` cannot both be enabled. To post the current-run gate report on an associated pull request, give the token either `pull-requests: write` or `issues: write` and set `comment-on-pr: 'true'`.

## Inputs

| Input | Default | Purpose |
|---|---|---|
| `github-token` | required | Reads workflow runs/logs; needs Actions write only when rerunning. |
| `run-id` | workflow-run event ID | Workflow run to inspect. |
| `repository` | current repository | Repository in `owner/name` form. |
| `auto-rerun` | `false` | Legacy all-or-nothing rerun mode. |
| `selective-rerun` | `false` | Reruns only individually safe high-confidence transient failed jobs. |
| `max-attempts` | `2` | Prevents rerun loops. |
| `comment-on-pr` | `true` | Posts the current-run Markdown report to the associated PR when permitted. |
| `history-runs` | `10` | Previous completed runs of the same workflow to inspect; capped at 50. |
| `policy-shadow-mode` | `false` | Runs the read-only same-workflow retrospective backtest. |
| `benchmark-mode` | `false` | Runs the read-only cross-repository backtest. |
| `benchmark-repositories` | current repository | Comma-, space-, or newline-separated `owner/name` repositories; capped at 50. |
| `benchmark-runs` | `20` | Completed workflow runs sampled per benchmark repository; capped at 50. |

## Outputs

Core outputs include the current-run safety decision, selective-rerun counts, history/fingerprint metrics, and Policy Learning recommendations. Shadow Mode additionally emits `shadow-decisions`, `shadow-evaluated-decisions`, `shadow-recoveries`, `shadow-false-positives`, `shadow-unknown-outcomes`, `shadow-observed-precision`, and `shadow-recoverable-failed-minutes`.

Benchmark Mode emits:

| Output | Meaning |
|---|---|
| `benchmark-repositories-analyzed` | Repositories successfully included. |
| `benchmark-repositories-skipped` | Requested repositories that could not be analyzed. |
| `benchmark-runs-analyzed` | Total completed workflow runs sampled. |
| `benchmark-failed-jobs` | First-attempt failed jobs observed. |
| `benchmark-shadow-decisions` | Simulated historical `AUTO_RERUN_ONCE` decisions. |
| `benchmark-evaluated-decisions` | Shadow decisions with an observed historical rerun outcome. |
| `benchmark-recoveries` | Evaluated decisions whose real rerun recovered. |
| `benchmark-false-positives` | Evaluated decisions whose real rerun did not recover. |
| `benchmark-unknown-outcomes` | Decisions without an observed rerun outcome. |
| `benchmark-observed-precision` | Recoveries divided by evaluated decisions. |
| `benchmark-decision-coverage` | Shadow decisions divided by first-attempt failed jobs. |
| `benchmark-evaluated-coverage` | Evaluated decisions divided by first-attempt failed jobs. |

## Safety model

The action fails closed. `UNKNOWN`, code failures, mixed evidence, low-confidence classifications, attempt caps, and side-effect signals block automatic reruns. Log evidence is redacted for common token/API-key patterns before it is included in reports or fingerprint inputs.

History, fingerprinting, Policy Learning, Shadow Mode, and Benchmark Mode are read-only. They read workflow runs, attempts, jobs, and logs through the GitHub API and do not persist them to an external database.

Policy recommendations do not override the runtime safety gate. A fingerprint with a historically strong recovery rate still cannot bypass side-effect protection or the attempt cap.

This tool cannot prove that rerunning arbitrary third-party workflows is safe. Its output is a conservative heuristic based on available GitHub job metadata and logs; evaluate it read-only before enabling reruns on important repositories.

## Validation

The action has unit coverage for transient failures, code failures, unknown failures, secret redaction, side-effect blocking, attempt caps, runtime accounting, historical transient-waste accounting, recurring failure detection, fingerprint stability under dynamic log values, fingerprint separation for different failures, real-vs-copied rerun detection, rerun-recovery metrics, Policy Learning thresholds, Shadow Mode look-back isolation, Benchmark Mode repository isolation, unknown counterfactual handling, and benchmark precision/coverage aggregation.

Selective Safe Rerun has also been tested end-to-end in GitHub Actions: a mixed run containing a transient network failure and a code regression caused only the transient job to execute again; the code-regression job remained blocked, and the attempt cap prevented a third loop.

Policy Shadow Mode has also been tested end-to-end with real GitHub workflow attempts: five earlier transient failures with successful real reruns formed the prior evidence, and the sixth historical case produced one evaluated shadow decision, one recovery, zero false positives, and observed precision `1.0000` in that controlled test.

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
