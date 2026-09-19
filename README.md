# CI Retry Gate

[![CI](https://github.com/othy19904-eng/workflow-failure-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/othy19904-eng/workflow-failure-lab/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/othy19904-eng/workflow-failure-lab)](https://github.com/othy19904-eng/workflow-failure-lab/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Stop blindly rerunning failed GitHub Actions.**

CI Retry Gate inspects failed jobs, decides whether a rerun is safe, and can rerun only failures that pass conservative provenance, side-effect, confidence, and attempt-limit checks.

### Why teams would use it

- **Blocks deterministic failures** instead of wasting another run on the same code error.
- **Fails closed on uncertainty**: unknown and low-confidence failures are not auto-rerun.
- **Checks where the transient evidence happened** before granting rerun authority.
- **Blocks side-effect workflows** such as deploy, publish, migration, and release paths.
- **Can rerun only the safe failed jobs**, not every failed job in the workflow.
- **Measures recurring failures and CI waste** from real history instead of guessing.

> Automatic reruns are **off by default**. You can start in read-only/report-only mode and enable write behavior later.

## 60-second start

Create a second workflow that listens for completed CI runs:

```yaml
name: CI Retry Gate

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

permissions:
  actions: read
  pull-requests: write

jobs:
  retry-gate:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - uses: othy19904-eng/workflow-failure-lab@v1
        with:
          github-token: ${{ github.token }}
          auto-rerun: 'false'
          selective-rerun: 'false'
```

That configuration analyzes the failed run and reports the decision without rerunning anything.

To enable reruns later, grant `actions: write` and opt into **one** rerun mode explicitly. Do not enable `auto-rerun` and `selective-rerun` together.

> Use `@v1` for the current stable v1 line, or pin an exact `v1.x.y` tag when you need an immutable dependency.


## Setup Doctor: validate before rollout

Before enabling retries, quarantine, ownership routing, or write behavior, run the read-only Setup Doctor against the checked-out repository:

```yaml
permissions:
  contents: read
  actions: read

steps:
  - uses: actions/checkout@v4

  - id: doctor
    uses: othy19904-eng/workflow-failure-lab/doctor@v1
    with:
      github-token: ${{ github.token }}
      frameworks: 'auto'
      junit-artifact-prefix: 'junit-results'
```

The doctor produces a GitHub step summary with one of:

- **READY** — no blocking setup problem was found.
- **WARN** — rollout can continue, but something deserves attention, such as missing visible JUnit artifact wiring or requested write permissions that the doctor deliberately refuses to probe by creating content.
- **BLOCKED** — a concrete prerequisite is missing or malformed, such as an undetected requested framework, Jest without `jest-junit`, unreadable Actions history, an invalid ownership map, or a missing/invalid quarantine manifest.

It detects pytest, Jest, and Vitest, validates the Jest JUnit reporter requirement, checks repository/Actions read access, inspects JUnit artifact wiring, and can validate optional ownership and quarantine configuration. For monorepos, point `working-directory` at the package root.

To preflight optional features without granting them write authority yet:

```yaml
- id: doctor
  uses: othy19904-eng/workflow-failure-lab/doctor@v1
  with:
    github-token: ${{ github.token }}
    frameworks: 'pytest,jest,vitest'
    flaky-ownership-routing: 'true'
    flaky-ownership-map: '.github/flaky-ownership.json'
    flaky-triage-comment: 'true'
    flaky-issue-lifecycle: 'true'
    rerun-mode: 'selective'
```

The summary prints the exact permission set and a recommended production configuration. The doctor remains **read-only**: it never proves write permission by creating a PR comment, Issue, rerun, or quarantine. `fail-on-blocked` defaults to `true`, while WARN checks never fail the job.

Outputs:

- `ready`
- `blocked-checks`
- `warnings`
- `detected-frameworks`
- `required-permissions`


## What makes it different from a retry loop?

| Blind retry | CI Retry Gate |
|---|---|
| Retries because something failed | Retries only when the failure passes a safety gate |
| Can hide deterministic failures | Blocks code regressions and low-confidence cases |
| Often ignores where the error occurred | Binds transient evidence to the failed execution step |
| Can repeat risky jobs | Blocks side-effect boundaries |
| Usually treats all failed jobs the same | Supports selective rerun of individually safe jobs |
| Gives little historical context | Tracks fingerprints, validated recoveries, and failed runtime |

## Decision model

The action classifies failed jobs into:

- `RUNNER_INFRA`
- `DEPENDENCY_NETWORK`
- `RESOURCE_TIMEOUT`
- `FLAKY_TEST`
- `CODE_REGRESSION`
- `UNKNOWN`

A high-confidence transient classification is still **not enough** by itself to authorize a rerun. Production rerun authority also requires confirmed execution provenance, no side-effect boundary, and remaining retry attempts.

Example fail-closed outcome:

```text
Decision: DO NOT AUTO-RERUN

unit-tests
  category: CODE_REGRESSION
  confidence: high
  rerun: blocked
  reason: deterministic failure evidence
```

## Safe rollout path

1. Start with `auto-rerun: 'false'` and `selective-rerun: 'false'`.
2. Observe reports on real failures.
3. Review how the gate classifies your CI.
4. Enable only the rerun mode you want, with `actions: write`.
5. Keep attempt limits and side-effect protection enabled.

## Flaky Test Intelligence (opt-in)

CI Retry Gate can now analyze **JUnit XML artifacts across GitHub Actions history** and rank individual tests by evidence-backed CI waste.

The detector does not label a test flaky merely because it failed once or because it passed after the code changed. Its strongest evidence is:

```text
same git SHA -> test fails -> later execution -> same test passes
```

A test becomes a human-reviewed `QUARANTINE_CANDIDATE` only after at least two same-SHA fail-to-pass recoveries and no revision with an unresolved persistent failure. Quarantine is never applied automatically.

### 1. Upload JUnit from the source CI workflow

Upload the report even when tests fail, and include the GitHub run attempt in the artifact name:

```yaml
- name: Run tests
  run: pytest --junitxml=junit.xml

- name: Upload JUnit
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: junit-results-attempt-${{ github.run_attempt }}
    path: junit.xml
```

Other frameworks are supported when they emit standard JUnit XML.

### 2. Enable history analysis in CI Retry Gate

```yaml
- uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    flaky-test-intelligence: 'true'
    junit-artifact-prefix: 'junit-results'
    flaky-history-runs: '20'
```

The GitHub step summary then shows the highest-waste tests, same-SHA recoveries, persistent-failure revisions, and one of:

- `QUARANTINE_CANDIDATE` — repeated recovery evidence, but human review is still required.
- `INVESTIGATE` — some recovery evidence exists but it is not yet strong enough.
- `DO_NOT_QUARANTINE` — evidence is absent or a persistent failure could represent a real regression.

For workflow reruns, artifacts without an `attempt-N` suffix are skipped because their execution provenance is ambiguous.


### 3. Optional temporary quarantine lifecycle

Detection and quarantine are deliberately separate. A test is never quarantined merely because the detector recommends it.

Enable lifecycle evaluation:

```yaml
- uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    flaky-test-intelligence: 'true'
    quarantine-lifecycle: 'true'
    quarantine-manifest: '.github/flaky-quarantine.json'
    quarantine-max-days: '14'
    quarantine-release-clean-shas: '3'
```

A maintainer approves a temporary quarantine by adding the test to the version-controlled manifest, normally through a reviewed pull request:

```json
{
  "version": 1,
  "entries": [
    {
      "test_id": "pkg.TestCart::test_total",
      "approved_by": "maintainer-login",
      "approved_at": "2026-09-19T12:00:00Z",
      "activated_run_id": 123456789,
      "expires_at": "2026-09-26T12:00:00Z",
      "reason": "Temporary isolation while the owner investigates."
    }
  ]
}
```

The lifecycle engine then evaluates every approved entry:

- `ACTIVE` — approval is valid, the TTL has not expired, and current evidence still supports quarantine.
- `EXPIRED` — the explicit expiry time has passed; the test is removed from the effective quarantine set.
- `RELEASED_HEALTHY` — enough later **distinct code revisions** are pass-only; the test is automatically removed from the effective set before expiry.
- `BLOCKED_REGRESSION` — a persistent failing revision appeared, so quarantine is suspended fail-closed instead of hiding a possible regression.
- `BLOCKED_UNVERIFIED` — current evidence is missing or no longer meets the quarantine threshold.

The action exposes `active-quarantine-tests-json` plus lifecycle counts so framework-specific adapters can consume the effective quarantine set. The lifecycle layer itself does **not** rewrite test source or silently add skip markers.

The manifest is read from the exact target workflow revision, so approval state is version-controlled and auditable. Repository branch protection/review rules can be used to control who is allowed to approve manifest changes.


### 4. Enforce quarantine without skipping the test

Wave 4 provides framework adapters that still execute every test, produce JUnit evidence, and change the CI result only when **all** attributable testcase failures are already in the effective `ACTIVE` quarantine set.

A non-quarantined failure always keeps CI red. A missing or malformed JUnit report, a collection/configuration failure with no attributable failing testcase, or suite-level failures that cannot be mapped to a testcase also fail closed.

#### pytest

```yaml
- id: flaky-policy
  uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    flaky-test-intelligence: 'true'
    quarantine-lifecycle: 'true'

- uses: othy19904-eng/workflow-failure-lab/adapters/pytest@v1
  with:
    active-tests-json: ${{ steps.flaky-policy.outputs.active-quarantine-tests-json }}
    test-command: 'python -m pytest -q'
```

The pytest adapter injects `--junitxml` unless the command already specifies a JUnit path.

#### Jest

Install `jest-junit` in the project, then:

```yaml
- uses: othy19904-eng/workflow-failure-lab/adapters/jest@v1
  with:
    active-tests-json: ${{ steps.flaky-policy.outputs.active-quarantine-tests-json }}
    test-command: 'npx jest --ci'
```

The adapter adds the `jest-junit` reporter and points it at the managed JUnit path.

#### Vitest

```yaml
- uses: othy19904-eng/workflow-failure-lab/adapters/vitest@v1
  with:
    active-tests-json: ${{ steps.flaky-policy.outputs.active-quarantine-tests-json }}
    test-command: 'npx vitest run'
```

The Vitest adapter enables the built-in JUnit reporter and manages its output path.

Each adapter uploads the resulting report as `junit-results-attempt-${{ github.run_attempt }}`, feeding the same evidence back into Flaky Test Intelligence on later runs. This closes the loop:

```text
detect -> approve -> enforce -> keep executing -> collect JUnit ->
observe recovery/regression -> auto-release or block quarantine
```

The adapters never use shell evaluation for `test-command`; it is tokenized and executed directly. Shell operators such as `&&`, pipes, or redirections are intentionally unsupported. Put complex setup in separate workflow steps.

For monorepos or packages that keep their test configuration below the repository root, set `working-directory` on any adapter. The test command runs from that directory while the managed JUnit path remains anchored to the GitHub workspace, so history collection still finds the report consistently.

```yaml
- uses: othy19904-eng/workflow-failure-lab/adapters/vitest@v1
  with:
    active-tests-json: ${{ steps.flaky-policy.outputs.active-quarantine-tests-json }}
    working-directory: 'packages/web'
    test-command: 'npx vitest run'
```


### 5. Compatibility policy

Adapter compatibility is exercised in GitHub Actions against multiple real framework majors, not inferred from unit tests.

| Adapter | CI-validated framework majors |
| --- | --- |
| pytest | 8, 9 |
| Jest | 29, 30 |
| Vitest | 4, 5 |

For every listed major, the compatibility workflow runs the real framework twice:

1. an intentional failure with no active quarantine must keep the gate red;
2. the exact testcase ID emitted by that framework's JUnit is then placed in the ACTIVE set, rerun, and must produce a green quarantine gate while still recording the failure.

The matrix intentionally installs the latest version available inside each tested major range on each CI run. This catches minor/patch drift inside supported majors instead of proving compatibility only with one frozen patch version.

The matrix currently uses Python 3.12 for the enforcement runtime and Node.js 22 for Jest/Vitest integration tests.


### 6. Stable `v1` remote-consumer gate

The repository also runs a packaging-level consumer workflow that invokes the stable release line through remote GitHub Action references:

- `othy19904-eng/workflow-failure-lab@v1`
- `othy19904-eng/workflow-failure-lab/adapters/pytest@v1`
- `othy19904-eng/workflow-failure-lab/adapters/jest@v1`
- `othy19904-eng/workflow-failure-lab/adapters/vitest@v1`

This is intentionally different from the local smoke tests that use `./adapters/...`. The remote gate verifies that the movable `v1` branch contains the packaged files consumers actually receive, that the root action can run with read-only Actions/content permissions when reruns are disabled, and that each adapter still preserves the red/green quarantine boundary.

For every adapter, the gate:

1. runs an intentional failing consumer test with an empty ACTIVE set and requires the adapter to fail;
2. independently extracts the real testcase ID from JUnit without importing CI Retry Gate code;
3. reruns the same test through the remote `@v1` adapter with that exact ID ACTIVE;
4. requires zero blocking failures and one quarantined failure;
5. verifies JUnit evidence is uploaded as an attempt-aware GitHub Actions artifact.

The `v1` branch is advanced only by fast-forward to a commit that has already passed the normal CI, compatibility matrix, and remote-consumer gate. It is never force-moved as part of this process.


### 7. Developer triage surface

When `flaky-test-intelligence: 'true'` is enabled, CI Retry Gate now turns the detector and lifecycle state into a bounded developer-facing triage surface.

The step summary includes a table with:

- test ID;
- current detector/lifecycle state;
- failure, same-SHA recovery, and persistent-failure evidence;
- estimated CI waste;
- a concrete next action.

The action also emits up to 10 GitHub workflow annotations so the highest-priority flaky/regression items are visible from the run without opening raw logs. Lifecycle decisions override detector recommendations in this view, so an active or blocked quarantine is never presented as a fresh candidate.

The new observational outputs are:

- `flaky-triage-items`
- `flaky-triage-annotations`
- `flaky-triage-comment-posted`

PR comments remain **opt-in**. To enable one deduplicated triage comment that is updated in place on later runs:

```yaml
permissions:
  contents: read
  actions: read
  pull-requests: write

steps:
  - uses: othy19904-eng/workflow-failure-lab@v1
    with:
      github-token: ${{ github.token }}
      flaky-test-intelligence: 'true'
      flaky-triage-comment: 'true'
```

If no pull request can be associated with the analyzed workflow run, or if the token cannot write the comment, the action emits a warning and leaves the underlying retry/quarantine decision unchanged.

The triage UI does not grant authority. A `QUARANTINE_CANDIDATE` still requires human approval in the manifest, `BLOCKED_REGRESSION` remains fail-closed, and ACTIVE tests continue to execute so later recovery or regression evidence stays observable.


### 8. Ownership + triage routing

Ownership routing is opt-in and remains read-only:

```yaml
- uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    flaky-test-intelligence: 'true'
    flaky-ownership-routing: 'true'
```

For each triage item, CI Retry Gate first looks for a stable JUnit `file` attribute and resolves that path through CODEOWNERS from the **exact analyzed revision**. GitHub's standard CODEOWNERS locations are checked in order:

- `.github/CODEOWNERS`
- `CODEOWNERS`
- `docs/CODEOWNERS`

When JUnit does not expose a file path, the file path is ambiguous, or CODEOWNERS has no matching owner, you can provide a framework-neutral fallback map at `.github/flaky-ownership.json`:

```json
{
  "version": 1,
  "rules": [
    {
      "test_pattern": "payments.*::*",
      "owners": ["@payments-team"],
      "route": "payments-ci"
    }
  ]
}
```

Use a custom map path with `flaky-ownership-map` when needed.

The triage table then adds **Owner** and **Route source**. Ownership is deliberately informational: it cannot authorize reruns or quarantines, it does not open or assign issues, and owners are rendered as Markdown code spans so PR comments do not automatically mention or notify them.

The action exposes:

- `flaky-owned-items`
- `flaky-unowned-items`
- `flaky-ownership-rules`
- `flaky-codeowners-path`

If multiple different source files are observed for the same test ID, the action refuses to guess a CODEOWNERS route and falls back to the explicit test-ID map or leaves the item `UNOWNED`.


### 9. Opt-in Issue lifecycle

CI Retry Gate can maintain one GitHub Issue per actionable flaky/regression test:

```yaml
permissions:
  contents: read
  actions: read
  issues: write

steps:
  - uses: othy19904-eng/workflow-failure-lab@v1
    with:
      github-token: ${{ github.token }}
      flaky-test-intelligence: 'true'
      flaky-ownership-routing: 'true'
      flaky-issue-lifecycle: 'true'
      flaky-issue-max-changes: '10'
```

The Issue uses a deterministic test-ID fingerprint, so later runs update the same Issue instead of creating duplicates. Actionable candidate/investigation/quarantine/regression states can create or reopen it. `DO_NOT_QUARANTINE` does not create a new Issue on its own. Only `RELEASED_HEALTHY` closes a managed Issue automatically.

Issue bodies carry the latest state, owners/routes, evidence counts, estimated waste, next action, and a link to the analyzed run. Owners are shown without automatic mentions or assignment.

Writes are bounded: the default maximum is 10 Issue changes per run, configurable from 1 to 50. Deferred changes are exposed through `flaky-issues-deferred`.


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

### Mechanism Causality Gate

A transient token is not accepted as mechanism evidence unless it is **causal and bound to the failed step**. For every ground-truth-evaluable UNKNOWN rerun sample, the gate requires:

- exactly one failed step with timing metadata;
- the mechanism-bearing log line to fall inside that failed-step time window;
- that line to be classified as direct causal operational evidence;
- the transient mechanism to be detected on that causal line itself.

This rejects false mechanism signals such as `--timeout=45m` CLI options, package names like `wait-timeout`, branch names containing `timeout`, or other descriptive text. A pattern receives `MECHANISM_CAUSALITY_EVIDENCE` when one or more ground-truth-evaluable rerun samples lack causal mechanism binding.

The gate is research-only and does not modify runtime rerun authority.

### Independent Replication Gate

A causally supported transient mechanism still does not qualify for classifier research from repeated evidence inside one workflow run. Promotion requires the same UNKNOWN pattern to have causally bound, ground-truth-evaluable evidence in at least **2 distinct workflow run IDs**.

The gate tracks two dimensions separately:

- `independent_runs`: distinct workflow run IDs with causally confirmed mechanism evidence;
- `independent_repositories`: distinct repositories contributing that evidence.

Two independent runs inside one repository can satisfy the mandatory replication gate. Cross-repository replication is reported as stronger external evidence but is not mandatory yet, because a genuine transient mechanism may repeat inside one project before appearing elsewhere.

Multiple jobs, rerun attempts, or duplicated samples from the same run ID never inflate the independent-run count. `INDEPENDENT_REPLICATION` blocks promotion until the minimum is reached.

This gate is research-only and does not change runtime classification or rerun authority.

### Targeted Replication Search

Once a real causal mechanism is pinned, Benchmark Mode can search specifically for independent evidence of that mechanism family across the rerun-enriched corpus. Set `benchmark-target-mechanism` to a reason such as `SERVER_5XX`.

The search includes only UNKNOWN failures whose mechanism was causally bound inside the failed-step window and whose rerun outcome is ground-truth-evaluable. Side-effect-contaminated matches remain visible but are excluded from usable replication counts.

It reports:

- distinct workflow run IDs with usable causal evidence;
- distinct repositories;
- validated recoveries versus failed-again outcomes;
- mechanism-family recovery rate;
- whether independent-run replication is confirmed;
- whether replication crosses repository boundaries;
- pattern IDs and signatures contributing to the mechanism family.

Mechanism-family replication is deliberately separate from exact-pattern promotion. Finding the same `SERVER_5XX` mechanism under different commands or repositories strengthens research evidence, but it does not automatically create or authorize a runtime classifier rule.

The current pinned corpus demonstrates this distinction: `SERVER_5XX` is independently replicated across Serde and Traefik, while each exact normalized UNKNOWN pattern still has only one pinned occurrence.

### SERVER_5XX Classifier Rule Research

After mechanism-family replication, Benchmark Mode can evaluate the shadow-only rule `SERVER_5XX_CAUSAL_UNKNOWN` by setting `benchmark-research-rule` to that value.

The hypothesis is deliberately narrow:

`UNKNOWN + failed-step causal SERVER_5XX evidence → proposed DEPENDENCY_NETWORK`

The rule is **not installed into `classify_log()`**. It is evaluated only against historical samples. The report separates:

- natural-sample matches, to estimate how often the rule would affect UNKNOWN coverage;
- rerun-enriched matches with Ground Truth, to measure validated recoveries and failed-again false positives;
- unknown/unverified outcomes, excluded from the precision denominator;
- independent run and repository counts;
- side-effect matches, which remain authority-blocked but are not treated as classifier false positives.

This separation is intentional: classification asks what kind of failure occurred; authority asks whether a real-world rerun is admissible. A strong shadow precision result does not by itself grant rerun authority or change production classification.

### SERVER_5XX Counterexample Search

Every `SERVER_5XX_CAUSAL_UNKNOWN` research run also performs a broader falsification search across **all runtime categories**, not only `UNKNOWN`.

The search looks for two distinct counterexample classes:

- **Outcome counterexample** — causal `SERVER_5XX` is ground-truth-evaluable and the rerun fails again. This is the strongest direct falsifier of the transient-rule hypothesis.
- **Classification contradiction** — causal `SERVER_5XX` coexists with a non-transient, non-`UNKNOWN` category such as `CODE_REGRESSION`. This is diagnostic evidence for manual inspection, not automatically a false positive.

Side-effect matches are reported separately because they affect rerun authority rather than failure classification. Unknown or unverified rerun outcomes remain outside the recovery-rate denominator.

The falsification search is read-only. It does not install the proposed classifier rule and does not weaken any runtime authority gate.

### Pinned Research Corpus

Moving recent-run windows are useful for discovery but unstable for regression testing. High-value real cases are therefore pinned as immutable research fixtures with public repository/run/job identifiers and expected safety semantics.

The pinned corpus now contains two independent `SERVER_5XX` cases:

- `serde-rs/serde` run `34427119351`, job `Outdated`: artifact-attestation verification failed on GitHub API `HTTP 500: Server Error`; the same failed step succeeded on attempt 2.
- `traefik/traefik` run `34857150924`, job `lint`: `golangci-lint-action` failed while downloading its binary after repeated `Unexpected HTTP response: 504`; the same `golangci-lint` step succeeded on attempt 2.

Both fixtures must remain:

- runtime classification: `UNKNOWN`;
- side-effect risk: false;
- outcome: `VALIDATED_RECOVERY`;
- transient mechanism: `SERVER_5XX`;
- mechanism causality: confirmed inside the failed step.

Together they establish **mechanism-family replication across 2 independent workflow runs and 2 repositories, with 2/2 validated recoveries**. They do **not** automatically promote either exact UNKNOWN pattern: exact-pattern occurrence, ground-truth, and promotion thresholds remain separate.

Pinning a case is evidence preservation, not classifier promotion.

`INVESTIGATE_TRANSIENT_PATTERN` is emitted only when the UNKNOWN signature is stable, semantically specific, has positive transient-mechanism evidence, that mechanism is causally bound inside every ground-truth-evaluable failed-step sample, the evidence spans at least 2 distinct workflow runs, the pattern appears at least 3 times, has at least 3 ground-truth-evaluable reruns, at least 80% validated recovery, and no side-effect occurrence is present. Cross-repository replication is reported but not mandatory. This status is **research evidence only**: it does not change the runtime classifier and never grants rerun authority.

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
| `benchmark-unknown-promotion-blocker-mechanism-causality-evidence` | Patterns blocked because transient mechanism tokens were not causally bound inside every ground-truth-evaluable failed-step sample. |
| `benchmark-unknown-promotion-blocker-independent-replication` | Patterns blocked because causally supported evidence has not replicated across at least two distinct workflow run IDs. |
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

The action has unit coverage for transient failures, code failures, unknown failures, causal-vs-non-causal log evidence, retry-authority execution provenance, classification-independent failure-step outcome provenance, recovery ground-truth validation, unverified/inconsistent recovery exclusion, first-gate coverage attribution, evidence-gap versus authority-boundary separation, UNKNOWN cause decomposition, cause-family aggregation, UNKNOWN promotion blocker attribution, Semantic Promotion Gate filtering, Transient Mechanism Gate evidence, Mechanism Causality Gate binding, Independent Replication Gate run-ID deduplication and cross-repository tracking, CLI/test/package/branch timeout-token regressions, deterministic-mechanism blocking, promotion-distance accounting, weak transient evidence discounting, secret redaction, side-effect blocking, attempt caps, runtime accounting, historical transient-waste accounting, recurring failure detection, fingerprint stability under dynamic log values, fingerprint separation for different failures, real-vs-copied rerun detection, Policy Learning thresholds, Shadow Mode look-back isolation, Benchmark Mode repository isolation, unknown counterfactual handling, benchmark precision/coverage aggregation, UNKNOWN signature extraction, cross-repository UNKNOWN clustering, promotion thresholds, and UNKNOWN side-effect guards.

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


## License

CI Retry Gate is released under the MIT License. See [LICENSE](LICENSE).
