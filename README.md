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

## Causal Evidence Layer

Before category scoring, CI Retry Gate classifies each cleaned log line as `CAUSAL`, `AMBIGUOUS`, or `NON_CAUSAL`.

Clearly non-causal material such as shell comments, GitHub runner grouping metadata, Sphinx documentation roles, echoed/source-code examples, and simple configuration values is excluded from failure scoring. Operational forms such as `Error:`, `npm ERR!`, `curl: (...)`, `read tcp`, `dial tcp`, GitHub `##[error]` annotations, and explicit process failures remain eligible evidence.

Weak transient phrases such as a bare `connection timed out` line are treated only as hints unless stronger operational context is present. This prevents documentation or fixtures containing words like `timeout` from accumulating enough score to authorize a rerun.

The layer is intentionally fail-closed: ambiguous evidence may reduce coverage, but it cannot independently promote a job to high-confidence transient status.

## Execution Provenance Gate

High-confidence transient classification is no longer sufficient by itself to authorize a rerun. CI Retry Gate binds the transient evidence back to the GitHub Actions step that actually failed.

For failed jobs, the gate uses runner timestamps plus step `started_at` / `completed_at` metadata. A transient signal is `CONFIRMED` only when it falls inside the time window of a step whose conclusion is `failure`, `timed_out`, or `cancelled`. When available, the report also records the step name, the `Run ...` command group, and the process exit line.

The gate fails closed:

- `CONFIRMED` — transient evidence is bound to the failed execution step.
- `UNAVAILABLE` — required step timing or timestamped evidence is missing.
- `MISMATCH` — timestamped transient evidence exists, but outside every failed-step window.
- `NOT_APPLICABLE` — the job is not a high-confidence transient candidate.

Automatic and selective reruns require `CONFIRMED` provenance in addition to the existing transient-confidence, side-effect, and retry-attempt guards. Benchmark Mode tracks `UNCONFIRMED_EXECUTION_PROVENANCE` separately so lost coverage can be investigated without weakening the safety boundary.

Execution Provenance is an **authority signal**. It is deliberately not reused as the sole source of historical outcome truth.

### Failure-Step Outcome Provenance

For outcome measurement, CI Retry Gate separately identifies the GitHub step that failed from job-step metadata, independent of the runtime classifier:

- `FAILURE_STEP_CONFIRMED` — exactly one named failed step is present;
- `FAILURE_STEP_AMBIGUOUS` — multiple failed steps prevent unique attribution;
- `FAILURE_STEP_UNAVAILABLE` — failed-step metadata is missing.

Failure-Step Outcome Provenance never authorizes a rerun. An `UNKNOWN` failure may therefore have a confirmed failed step for historical measurement while remaining fully blocked from automatic rerun.

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
8 occurrences · 5 real reruns · 4 later successes · 3 validated recoveries · 31.20 failed minutes
```

This distinction is intentional: **failed runtime is not automatically waste**. A real code regression can be useful CI work. `historical-transient-waste-minutes` counts only failures classified with high confidence as runner/infrastructure or dependency/network failures.

The default history window is 10 previous completed runs and can be increased up to 50.

## Recovery Ground-Truth Layer

A later successful rerun is not automatically counted as evidence that the original failure was transient. Recovery Ground Truth separates **observed success** from **validated recovery**.

A recovery is `VALIDATED_RECOVERY` only when:

- Failure-Step Outcome Provenance uniquely identifies the original failed step;
- the same job genuinely executed again rather than being copied untouched by GitHub;
- that same failed step appears in the later execution and completes successfully.

This validation is classification-independent. It can validate the historical outcome of an `UNKNOWN` failure without changing that failure's runtime retry authority.

Other outcomes remain explicit:

- `NOT_RECOVERED` — the genuine rerun executed but did not succeed;
- `UNVERIFIED_RECOVERY` — the later job succeeded, but failure-step or rerun-step metadata is insufficient;
- `INCONSISTENT_RECOVERY` — the later job succeeded without successfully re-executing the step tied to the original failure;
- `NOT_OBSERVED` — no genuine later execution was observed.

`UNVERIFIED_RECOVERY` and `INCONSISTENT_RECOVERY` are excluded from precision and policy-learning denominators. They are not counted as successes or failures. This prevents an unrelated later success from inflating measured retry precision.

## Coverage Attribution Layer

Coverage Attribution explains **where safe-candidate coverage is lost** without changing any rerun decision. For every failure in the rerun-enriched benchmark, it records the first limiting layer in pipeline order:

- `CLASSIFICATION_UNKNOWN` — no known failure category reached the classifier threshold;
- `NON_TRANSIENT_CATEGORY` — the known category is outside the conservative transient allow-list;
- `CODE_REGRESSION` — deterministic code-regression evidence blocks retry authority;
- `INSUFFICIENT_CAUSAL_EVIDENCE` — a transient category is present, but the selected evidence has no directly causal line;
- `LOW_TRANSIENT_CONFIDENCE` — causal support exists, but transient confidence is still below high;
- `UNCONFIRMED_EXECUTION_PROVENANCE` — high-confidence transient evidence cannot be bound to the failed execution step;
- `SIDE_EFFECT_BOUNDARY` — the evidence gates pass, but the workflow crosses a push/PR/deploy/publish or other real-world authority boundary;
- `ELIGIBLE` — all measured layers pass.

The layer also labels each bucket as an `EVIDENCE_GAP`, `DETERMINISTIC_BLOCKER`, `POLICY_BOUNDARY`, `AUTHORITY_BOUNDARY`, or `ELIGIBLE`. Raw later successes and Recovery Ground-Truth outcomes are shown separately, so a high number of later successes cannot by itself justify weakening a gate.

Coverage Attribution is diagnostic only. It does not grant rerun authority and does not override a later side-effect boundary.

## Policy Learning

Policy Learning turns fingerprint history into a conservative recommendation for each fingerprint:

- `AUTO_RERUN_ONCE`
- `MANUAL_REVIEW`
- `DO_NOT_AUTO_RERUN`

`AUTO_RERUN_ONCE` is recommended only when all of the following are true:

- the fingerprint belongs to `RUNNER_INFRA` or `DEPENDENCY_NETWORK`;
- at least 5 **ground-truth-evaluable** reruns were observed;
- at least 80% of those evaluable reruns are `VALIDATED_RECOVERY`;
- at least 80% of the fingerprint occurrences were classified with high confidence;
- no side-effect signal was observed.

Policy Learning is advisory only. It does not silently change the selective-rerun safety gate or enable reruns by itself.

GitHub can copy an untouched job into a later workflow attempt when another job is rerun. CI Retry Gate therefore counts a rerun sample only when the same job has a genuinely different `started_at` time in a later attempt. Recovery Ground Truth then performs the stronger step-level consistency check above.

## Policy Shadow Mode

`policy-shadow-mode: 'true'` runs a read-only retrospective backtest. For each historical point it uses only evidence older than that point, then evaluates a later rerun through Recovery Ground Truth. Unobserved, unverified, or inconsistent later outcomes remain `UNKNOWN` rather than being guessed.

Shadow Mode reports decisions, ground-truth-evaluated decisions, validated recoveries, observed failed reruns, unknown outcomes, precision, and the failed-job runtime represented by validated recoveries. It never triggers a rerun.

## Benchmark Mode

`benchmark-mode: 'true'` extends the same shadow backtest across a list of repositories. It is read-only and keeps Policy Learning **repository-local**: evidence from repository A cannot promote a fingerprint in repository B.

Benchmark Mode samples completed workflow runs, reads first-attempt failed jobs, detects real later attempts of the same job, and reports:

- repositories and completed runs analyzed;
- first-attempt failed jobs;
- shadow `AUTO_RERUN_ONCE` decisions;
- evaluated decisions with a ground-truth-evaluable rerun outcome;
- validated recoveries, observed failed reruns, and unknown/unverified outcomes;
- ground-truth precision;
- decision coverage and evaluated coverage;
- **coverage attribution** showing the first limiting pipeline layer for every rerun-enriched failure;
- **rejection intelligence** for failures that were blocked from auto-rerun;
- blocked failures that later recovered, failed again, or had no observable rerun outcome;
- rejection reasons such as side-effect risk, code regression, low-confidence transient, unknown classification, and other non-transient categories;
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

**Ground-truth precision is not overall classifier accuracy.** It is `validated recoveries / ground-truth-evaluable AUTO_RERUN_ONCE decisions`. Unobserved, unverified, and inconsistent outcomes are excluded rather than counted as successes or failures. Benchmark results describe only the sampled history and are not a guarantee of future behavior.

A **blocked recovery** is also not evidence that the block was wrong. A code regression, side-effect workflow, or ambiguous failure can succeed on a later rerun for unrelated reasons. Rejection Intelligence treats recovered blocked cases as places to investigate for safer coverage improvements, not as automatic promotion evidence.

## Unknown Failure Intelligence

Benchmark Mode now extracts redacted, normalized error-like signatures from failures that remain `UNKNOWN`, instead of treating every unknown case as one opaque bucket. It groups recurring signatures across the sampled repositories and compares them with observed real rerun outcomes.

For each UNKNOWN pattern it reports:

- stable pattern ID and normalized signature;
- occurrences and number of repositories;
- ground-truth-evaluable reruns;
- validated recoveries, repeated failures, and unknown outcomes;
- side-effect occurrences;
- an advisory status;
- the primary promotion blocker, the complete blocker set, and the numeric gap to classifier-research eligibility.

UNKNOWN Cause Decomposition adds a second diagnostic view across those same failures. It assigns one cause family without changing runtime classification:

- `NO_STABLE_ERROR_EVIDENCE`
- `AUTH_PERMISSION`
- `GIT_VCS`
- `COMMAND_CONFIG`
- `TEST_BUILD`
- `PACKAGE_TOOL`
- `TOOL_ACTION_SPECIFIC`
- `AMBIGUOUS_OPERATIONAL`

Each family reports occurrences, repository count, ground-truth outcomes, side-effect occurrences, and representative normalized signatures. These families are research buckets only: an UNKNOWN failure remains UNKNOWN until a separate classifier rule is justified and tested.

### UNKNOWN Promotion Blocker Attribution

Promotion readiness is decomposed into explicit blockers:

- `NO_STABLE_SIGNATURE`
- `INSUFFICIENT_OCCURRENCES`
- `INSUFFICIENT_GT_RERUNS`
- `RECOVERY_RATE_BELOW_THRESHOLD`
- `SEMANTIC_EVIDENCE_QUALITY`
- `TRANSIENT_MECHANISM_EVIDENCE`
- `SIDE_EFFECT_CONTAMINATION`
- `ELIGIBLE_FOR_CLASSIFIER_RESEARCH` when no blocker remains.

The benchmark reports all blockers for each pattern, a primary blocker, and the remaining gap such as `+1 occurrence`, `+2 GT reruns`, or a recovery-rate deficit. Patterns with exactly one remaining blocker are counted separately as near-promotion candidates.

### Semantic Promotion Gate

Promotion also requires at least one signature segment that describes a **specific failure**, not merely text that happens to contain failure words. The semantic gate blocks patterns composed only of:

- generic runner wrappers such as `Process completed with exit code ...`;
- generic cancellation annotations such as `The operation was canceled`;
- successful test lines such as `test ... cannot_publish ... ok`;
- command-source text such as `printf "... command not found ..."` that describes what a script prints rather than an observed failure.

Mixed signatures are not discarded if they still contain a specific failure segment. This gate is research-only and does not modify runtime classification or rerun authority.

### Transient Mechanism Gate

Semantic specificity is still not proof of transience. Promotion therefore requires **positive evidence of a temporary failure mechanism** such as:

- timeout / deadline exceeded;
- connection reset/refused/broken pipe;
- DNS resolution failure;
- HTTP 5xx server failure;
- rate limiting / HTTP 429;
- temporary/service unavailability;
- network EOF / TLS handshake timeout.

Diagnostic cause families that usually indicate deterministic state — `AUTH_PERMISSION`, `COMMAND_CONFIG`, `TEST_BUILD`, and `GIT_VCS` — are blocked unless the signature itself contains stronger direct transient-mechanism evidence. Other specific failures without transient evidence remain `TRANSIENT_MECHANISM_UNPROVEN`.

The gate is research-only: it neither changes runtime classification nor grants rerun authority.

`INVESTIGATE_TRANSIENT_PATTERN` is emitted only when the UNKNOWN signature is stable, semantically specific, has positive transient-mechanism evidence, appears at least 3 times, has at least 3 ground-truth-evaluable reruns, at least 80% validated recovery, and no side-effect occurrence is present. This status is **research evidence only**: it does not change the runtime classifier and never grants rerun authority.

This creates a controlled path from `UNKNOWN` → repeated evidence → candidate classifier rule → separate testing, rather than weakening the production safety gate from a handful of recoveries.

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
| `benchmark-evaluated-decisions` | Shadow decisions with a ground-truth-evaluable rerun outcome. |
| `benchmark-recoveries` | Evaluated decisions with `VALIDATED_RECOVERY`. |
| `benchmark-false-positives` | Evaluated decisions with an observed failed rerun. |
| `benchmark-unknown-outcomes` | Decisions with no rerun or an unverified/inconsistent later success. |
| `benchmark-observed-precision` | Validated recoveries divided by ground-truth-evaluated decisions. |
| `benchmark-decision-coverage` | Shadow decisions divided by first-attempt failed jobs. |
| `benchmark-evaluated-coverage` | Evaluated decisions divided by first-attempt failed jobs. |
| `benchmark-rerun-blocked` | Rerun-enriched failures blocked from becoming safe candidates. |
| `benchmark-rerun-blocked-recovered` | Blocked failures that later recovered after a real rerun. |
| `benchmark-rerun-blocked-failed-again` | Blocked failures that failed again after a real rerun. |
| `benchmark-rerun-blocked-unknown` | Blocked failures without an observable real rerun outcome. |
| `benchmark-coverage-evidence-gaps` | Failures whose first limiting layer is classification, causal support, confidence, or execution provenance. |
| `benchmark-coverage-classification-unknown` | Failures first limited by UNKNOWN classification. |
| `benchmark-coverage-non-transient` | Failures first limited by a known category outside the transient allow-list. |
| `benchmark-coverage-code-regression` | Failures first limited by deterministic code-regression evidence. |
| `benchmark-coverage-causal-evidence` | Transient failures first limited by missing directly causal selected evidence. |
| `benchmark-coverage-low-confidence` | Causally supported transient failures first limited by confidence below high. |
| `benchmark-coverage-unconfirmed-provenance` | High-confidence transient failures first limited by execution provenance. |
| `benchmark-coverage-side-effect-boundary` | Evidence-qualified transient failures first limited by an authority boundary. |
| `benchmark-coverage-eligible` | Failures passing all measured attribution layers. |
| `benchmark-rejection-side-effect` | Failures blocked by workflow/job side-effect risk. |
| `benchmark-rejection-code-regression` | Failures blocked as code regressions. |
| `benchmark-rejection-low-confidence-transient` | Transient-category failures blocked because confidence was not high. |
| `benchmark-rejection-unknown-classification` | Failures blocked because classification stayed UNKNOWN. |
| `benchmark-rejection-non-transient` | Other non-auto-rerun categories such as resource/flaky-test classes. |
| `benchmark-unknown-patterns` | Distinct normalized UNKNOWN signatures found in the benchmark samples. |
| `benchmark-unknown-repeated-patterns` | UNKNOWN signatures observed at least twice. |
| `benchmark-unknown-evaluated-reruns` | UNKNOWN cases with a ground-truth-evaluable rerun outcome. |
| `benchmark-unknown-recoveries` | UNKNOWN cases with a validated recovery. |
| `benchmark-unknown-failed-again` | UNKNOWN cases whose real rerun failed again. |
| `benchmark-unknown-promotion-candidates` | Advisory UNKNOWN patterns meeting the conservative investigation threshold. |
| `benchmark-unknown-promotion-candidate-ids` | Comma-separated IDs of those advisory patterns. |
| `benchmark-unknown-near-promotion-candidates` | UNKNOWN patterns exactly one blocker away from classifier-research eligibility. |
| `benchmark-unknown-promotion-blocker-no-stable-signature` | Patterns blocked because no stable normalized error signature exists. |
| `benchmark-unknown-promotion-blocker-insufficient-occurrences` | Patterns blocked because fewer than three occurrences are available. |
| `benchmark-unknown-promotion-blocker-insufficient-gt-reruns` | Patterns blocked because fewer than three ground-truth-evaluable reruns are available. |
| `benchmark-unknown-promotion-blocker-recovery-rate-below-threshold` | Patterns blocked because validated recovery rate is below 80%. |
| `benchmark-unknown-promotion-blocker-semantic-evidence-quality` | Patterns blocked because the signature lacks specific failure semantics after filtering wrappers, successful test lines, and command-source text. |
| `benchmark-unknown-promotion-blocker-transient-mechanism-evidence` | Patterns blocked because no independent transient mechanism such as timeout, reset, DNS failure, 5xx, rate limiting, or temporary unavailability is evidenced. |
| `benchmark-unknown-promotion-blocker-side-effect-contamination` | Patterns blocked because at least one occurrence crossed a side-effect boundary. |
| `benchmark-unknown-promotion-blocker-eligible-for-classifier-research` | Patterns satisfying all advisory evidence thresholds for classifier research. |
| `benchmark-unknown-cause-no-stable-error-evidence` | UNKNOWN failures with no stable error-like evidence after semantic filtering. |
| `benchmark-unknown-cause-auth-permission` | UNKNOWN failures grouped diagnostically as authentication/permission errors. |
| `benchmark-unknown-cause-git-vcs` | UNKNOWN failures grouped diagnostically as Git/version-control errors. |
| `benchmark-unknown-cause-command-config` | UNKNOWN failures grouped diagnostically as command/configuration errors. |
| `benchmark-unknown-cause-test-build` | UNKNOWN failures grouped diagnostically as test/build errors. |
| `benchmark-unknown-cause-package-tool` | UNKNOWN failures grouped diagnostically as package/dependency-tool errors. |
| `benchmark-unknown-cause-tool-action-specific` | UNKNOWN failures grouped diagnostically as recognized tool/action errors. |
| `benchmark-unknown-cause-ambiguous-operational` | UNKNOWN failures with stable operational evidence not matching another family. |

## Safety model

The action fails closed. `UNKNOWN`, code failures, mixed evidence, low-confidence classifications, attempt caps, and side-effect signals block automatic reruns. Log evidence is redacted for common token/API-key patterns before it is included in reports or fingerprint inputs.

History, fingerprinting, Policy Learning, Shadow Mode, and Benchmark Mode are read-only. They read workflow runs, attempts, jobs, and logs through the GitHub API and do not persist them to an external database.

Policy recommendations do not override the runtime safety gate. A fingerprint with a historically strong recovery rate still cannot bypass side-effect protection or the attempt cap.

This tool cannot prove that rerunning arbitrary third-party workflows is safe. Its output is a conservative heuristic based on available GitHub job metadata and logs; evaluate it read-only before enabling reruns on important repositories.

## Validation

The action has unit coverage for transient failures, code failures, unknown failures, causal-vs-non-causal log evidence, retry-authority execution provenance, classification-independent failure-step outcome provenance, recovery ground-truth validation, unverified/inconsistent recovery exclusion, first-gate coverage attribution, evidence-gap versus authority-boundary separation, UNKNOWN cause decomposition, cause-family aggregation, UNKNOWN promotion blocker attribution, Semantic Promotion Gate filtering, Transient Mechanism Gate evidence, deterministic-mechanism blocking, promotion-distance accounting, weak transient evidence discounting, secret redaction, side-effect blocking, attempt caps, runtime accounting, historical transient-waste accounting, recurring failure detection, fingerprint stability under dynamic log values, fingerprint separation for different failures, real-vs-copied rerun detection, Policy Learning thresholds, Shadow Mode look-back isolation, Benchmark Mode repository isolation, unknown counterfactual handling, benchmark precision/coverage aggregation, UNKNOWN signature extraction, cross-repository UNKNOWN clustering, promotion thresholds, and UNKNOWN side-effect guards.

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
