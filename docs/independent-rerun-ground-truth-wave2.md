# Independent Rerun Ground Truth — Wave 2

Date: 2026-09-28

## Purpose

Wave 1 showed that recoverable failures were not concentrated in production
`UNKNOWN`; 4 of 5 evaluable recoveries were classified `CODE_REGRESSION`.

Wave 2 asks whether that pattern replicates in different public repositories and,
more importantly, whether the recovered cases are actually relevant to historical
test evidence rather than pre-test or aggregation failures.

No production policy is changed by this experiment.

## Independent repositories

Wave 2 uses repositories not present in Wave 1:

- `OCHA-DAP/hdx-ckan`
- `metabase/metabase`
- `akash-network/console`

Selected rerun runs: **5**

Ground-truth-evaluable failed jobs: **6**

## Aggregate ground truth

```text
validated recoveries:          6
failed-again outcomes:         0

CODE_REGRESSION recoveries:    2
UNKNOWN recoveries:            3
DEPENDENCY_NETWORK recoveries: 1
```

Every Wave 2 candidate remained blocked by the production side-effect boundary:

```text
validated recoveries rejected as SIDE_EFFECT_RISK: 6
production authorization changes:                  0
```

This means recovery evidence does not imply retry authority.

## Case breakdown

| Repository | Run | Failed job | Production category | Confidence | Ground truth | Production rejection |
|---|---:|---|---|---|---|---|
| OCHA-DAP/hdx-ckan | 36440993676 | `test` | `UNKNOWN` | low | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |
| metabase/metabase | 36430245006 | `app-db-tests / Postgres 14.x EE App DB Tests (Part 3)` | `CODE_REGRESSION` | high | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |
| akash-network/console | 36240952224 | `validate (api) / validate` | `CODE_REGRESSION` | high | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |
| akash-network/console | 36240952224 | `validate (indexer) / test-build` | `DEPENDENCY_NETWORK` | medium | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |
| akash-network/console | 36240952224 | `validate (indexer) / result` | `UNKNOWN` | low | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |
| akash-network/console | 36240952224 | `validate (api) / result` | `UNKNOWN` | low | `VALIDATED_RECOVERY` | `SIDE_EFFECT_RISK` |

## Relevance filtering

The raw category totals are not sufficient for Historical Flakiness research.

### OCHA UNKNOWN

The OCHA failure occurred during environment/container setup. The job exited while
preparing the CKAN environment, before a usable failing-test history was produced.

Therefore:

```text
UNKNOWN recovery
!=
historical-test-evidence candidate
```

### Akash UNKNOWN

The two Akash `result` jobs are aggregation/result jobs. Their logs summarize
upstream validation outcomes rather than identify a concrete failing testcase.

Therefore they are not evidence that historical per-test behavior would have reduced
an UNKNOWN decision.

### Metabase CODE_REGRESSION — exact-test contradiction

Metabase provides the strongest Wave 2 case.

Attempt 1 produced a real JUnit-backed failure:

```text
metabase.setup-rest.api-test / setup-with-empty-cache-test
```

The CI Conductor quarantine gate reported:

```text
1 failing test
NOT quarantined
VERDICT: FAIL
```

Production classification for the failed job:

```text
CODE_REGRESSION / high
```

On GitHub Actions attempt 2, Metabase performed a granular rerun of exactly the
previously failing testcase:

```text
Granular rerun of previously-failed tests:
[metabase.setup-rest.api-test/setup-with-empty-cache-test]
```

Observed result:

```text
3 assertions, 0 failures, 0 errors
```

The same testcase was subsequently reported as passed.

This is direct evidence that ordinary regression-shaped test syntax can conflict with
observed same-run recovery.

It does **not** prove the original failure was harmless, and it does not authorize a
retry.

## Cross-wave view

Wave 1 and Wave 2 together now contain:

```text
independent repositories sampled:        6
selected rerun runs:                    12
ground-truth-evaluable failed jobs:     11
validated recoveries:                   11

CODE_REGRESSION recoveries:              6
UNKNOWN recoveries:                      4
DEPENDENCY_NETWORK recoveries:           1
```

This targeted rerun-enriched sample must not be interpreted as natural prevalence.

More important than the raw category counts is the semantic relevance:

- multiple UNKNOWN recoveries are pre-test or aggregation failures;
- `CODE_REGRESSION` recoveries recur across independent repositories;
- exact testcase-level fail→pass evidence is now observed independently in
  DataDog and Metabase.

## Decision after Wave 2

The original research hypothesis:

```text
Historical Flakiness mainly reduces UNKNOWN
```

is **not supported** by the independent evidence collected so far.

A narrower hypothesis has now earned further investigation:

```text
Current testcase failure
        ↓
regression-shaped evidence
        ↓
CODE_REGRESSION / BLOCK
        ↓
strictly-prior or same-run historical test evidence
shows validated fail→pass behavior
        ↓
HISTORICAL_REGRESSION_CONTRADICTION
        ↓
authorization unchanged
```

The role of such evidence would be to challenge epistemic certainty, not grant
execution authority.

## Architectural gate

Wave 2 provides enough cross-repository evidence to justify a **read-only research
shadow** for regression contradiction, but not production promotion.

Any implementation must preserve:

```text
CODE_REGRESSION
+ historical contradiction
!= ALLOW
```

and:

```text
authorization.changed = false
```

The shadow must not override:

- side-effect boundaries;
- provenance requirements;
- retry limits;
- consequence/admissibility policy;
- deterministic regression evidence from stronger sources.

## Proposed next step

Only after this evidence record is accepted should the project implement a minimal
**Historical Regression Contradiction Shadow v1**.

Its first scope should be narrow:

1. baseline production decision remains `BLOCK`;
2. baseline category is `CODE_REGRESSION`;
3. a concrete current failing testcase is identified;
4. historical evidence is temporally valid and identity-bound;
5. observed prior fail→pass recoveries are summarized;
6. contradiction is emitted as shadow evidence only;
7. production authorization remains unchanged.

Promotion to any action-affecting role would require a separate ground-truth study.
