# Historical Flakiness Shadow — External Consumer Validation

Date: 2026-09-28

## Purpose

Validate one narrow question with real GitHub Actions state transitions:

> Can strictly-prior flaky-test history add useful evidence to a production
> `BLOCK / UNKNOWN` retry decision without changing production authorization?

This validation uses the separate consumer repository:

- `achirothmane/ci-retry-gate-consumer-e2e`

The consumer repository does not contain the product source. The failure mechanism
is intentionally controlled so the ground truth is known. This is therefore an
**external-consumer engineering proof**, not yet independent market validation.

## Invariant under test

The production gate must remain unchanged:

```text
Production decision: BLOCK
Production evidence status: UNKNOWN
authorization.changed: false
```

Historical evidence is evaluated only in shadow mode.

## Experiment design

A dedicated GitHub Actions workflow produced the same logical testcase across
successive revisions.

For each generation:

1. attempt 1 emitted a JUnit failure;
2. the CI log remained unclassified by the production retry gate;
3. the workflow run was rerun on the same SHA;
4. attempt 2 emitted a JUnit pass;
5. the shadow evaluator used only strictly-prior observations.

The experiment advanced across separate commits so the third generation could be
evaluated against two completed prior fail→pass revisions.

## Observed sequence

| Generation | Run | Production baseline | Shadow result on attempt 1 | Ground truth |
|---|---:|---|---|---|
| 1 | [36467817083](https://github.com/achirothmane/ci-retry-gate-consumer-e2e/actions/runs/36467817083) | `BLOCK / UNKNOWN` | `NO_PRIOR_EVIDENCE` | attempt 2 passed |
| 2 | [36467975165](https://github.com/achirothmane/ci-retry-gate-consumer-e2e/actions/runs/36467975165) | `BLOCK / UNKNOWN` | `INSUFFICIENT_PRIOR_EVIDENCE` | attempt 2 passed |
| 3 | [36468338168](https://github.com/achirothmane/ci-retry-gate-consumer-e2e/actions/runs/36468338168) | `BLOCK / UNKNOWN` | `HISTORICAL_SUPPORT_PRESENT` | attempt 2 passed |

The clean generation-3 analysis job observed:

```text
INPUT_BASELINE_DECISION: BLOCK
INPUT_BASELINE_EVIDENCE_STATUS: UNKNOWN
generation=3
shadow=HISTORICAL_SUPPORT_PRESENT
supported=1
```

The production authorization remained fail-closed.

The same generation-3 controlled test then passed on GitHub Actions attempt 2,
providing observed recovery ground truth.

## What this proves

This experiment demonstrates that the current implementation can:

- preserve `BLOCK / UNKNOWN` in production;
- collect fail→pass evidence from real GitHub Actions rerun attempts;
- keep execution identity bound to run ID and run attempt;
- prevent future observations from being used as prior evidence;
- distinguish no history, insufficient history, and sufficient historical support;
- surface historical support without mutating retry authority;
- associate a shadow support signal with an observed later recovery.

For the controlled generation-3 sample:

```text
UNKNOWN baseline: 1
historical support signals: 1
observed recoveries after support: 1
observed failed-again after support: 0
production authorizations changed: 0
```

## What this does NOT prove

This sample is deliberately controlled and small. It does not establish:

- production precision across unrelated repositories;
- a general false-positive rate;
- that historical flakiness alone should ever authorize a retry;
- that the current two-recovery threshold is optimal;
- commercial demand or willingness to pay.

A single controlled recovery is evidence that the pipeline works, not evidence that
the rule is ready for production promotion.

## Next evidence gate

The next promotion question remains:

> Across independent real repositories, when the production gate is UNKNOWN,
> how often does historical support predict an observed same-state recovery without
> increasing false-positive retry candidates?

Required metrics for the next validation wave:

```text
UNKNOWN baseline cases
shadow support cases
shadow contradictions
ground-truth evaluable cases
validated recoveries
failed-again outcomes
unknown outcomes
shadow precision
UNKNOWN coverage delta
```

Production authorization must remain unchanged until that external backtest meets
the promotion criteria defined in ADR-0013.
