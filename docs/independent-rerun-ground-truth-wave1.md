# Independent Rerun Ground Truth — Wave 1

Date: 2026-09-28

## Question

The controlled external-consumer validation showed that strictly-prior flaky-test
history can add support to a production `BLOCK / UNKNOWN` decision without changing
authorization.

The first independent-repository question was therefore:

> In real public repositories, are recoverable rerun failures primarily hidden inside
> production `UNKNOWN`, such that historical flaky-test evidence could reduce the
> UNKNOWN gap?

This wave tests that hypothesis before any production promotion.

## Method

The sample uses real public GitHub Actions reruns from repositories not controlled by
this project. Existing `benchmark_mode.py` ground-truth logic was reused rather than
introducing a separate recovery definition.

For each selected workflow run:

1. inspect attempt-1 failed jobs;
2. classify the original failure using the production classifier;
3. bind the failed step and same-job rerun provenance;
4. observe whether a later attempt on the same workflow run recovered;
5. retain production rejection boundaries unchanged.

No external repository was modified and no rerun was triggered by this project.

## Sample

Repositories:

- `DataDog/dd-trace-js`
- `ckan/ckan`
- `open-telemetry/opentelemetry-dotnet`

Selected rerun runs: **7**

Ground-truth-evaluable failed jobs found: **5**

## Results

| Repository | Run | Failed job | Production category | Confidence | Production rejection | Ground truth |
|---|---:|---|---|---|---|---|
| DataDog/dd-trace-js | 36495931875 | `next (latest, 13.5.11)` | `CODE_REGRESSION` | medium | `CODE_REGRESSION` | `VALIDATED_RECOVERY` |
| DataDog/dd-trace-js | 36481666751 | `aws-sdk (oldest, s3)` | `CODE_REGRESSION` | medium | `CODE_REGRESSION` | `VALIDATED_RECOVERY` |
| ckan/ckan | 36104227064 | `Test (Pytest) / pytest (9)` | `CODE_REGRESSION` | medium | `CODE_REGRESSION` | `VALIDATED_RECOVERY` |
| ckan/ckan | 36103073165 | `Test (Pytest) / pytest (7)` | `CODE_REGRESSION` | high | `CODE_REGRESSION` | `VALIDATED_RECOVERY` |
| open-telemetry/opentelemetry-dotnet | 36425264396 | `build-test-project-experimental / build-test (windows-11-arm, net10.0)` | `UNKNOWN` | low | `SIDE_EFFECT_RISK` | `VALIDATED_RECOVERY` |

Aggregate:

```text
evaluable failed jobs:                5
validated recoveries:                 5
failed-again outcomes:                0

CODE_REGRESSION recoveries:           4
UNKNOWN recoveries:                   1

share of observed recoveries
classified CODE_REGRESSION:          80%
```

## Important qualification

The single `UNKNOWN` recovery was not a historical-test-evidence candidate.

Its attempt-1 failure occurred while installing .NET on a Windows ARM job, before
the test workload produced usable test-history evidence. The existing gate also
retained a side-effect-risk rejection boundary.

Therefore this sample provides **no independent support yet** for the original
hypothesis that historical flaky-test evidence primarily reduces production UNKNOWN.

## Independent ingestion proof

A separate public rerun in `DataDog/dd-trace-js` also exposed a real artifact
provenance pattern:

- two JUnit artifacts used the same unsuffixed name;
- one was produced during attempt 1 and the other during attempt 2;
- GitHub attempt time windows uniquely bound each artifact to its real attempt;
- 64 JUnit observations were ingested;
- one testcase showed a real same-SHA fail→pass recovery.

That evidence motivated and validated the trusted temporal artifact binding merged in
PR #106.

## What Wave 1 changes

It changes the **research question**, not production authority.

The current evidence points toward a different bottleneck:

```text
test fails
   ↓
assertion / ordinary test-failure syntax
   ↓
production classifier: CODE_REGRESSION
   ↓
BLOCK
   ↓
same SHA is rerun manually
   ↓
test recovers
```

This suggests historical test evidence may be more valuable as **contradiction
evidence against an apparently deterministic regression classification** than as a
generic UNKNOWN reducer.

That is only a research hypothesis.

## What Wave 1 does NOT justify

Wave 1 does not justify any of the following:

- `CODE_REGRESSION + flaky history => ALLOW`;
- weakening assertion/regression classification;
- bypassing side-effect, provenance, retry-limit, or consequence gates;
- automatic retry based on historical failure rate;
- production wiring of historical flakiness into `evidence_gate.py`;
- claiming an 80% population rate from this targeted sample.

The sample is small and intentionally rerun-enriched. It is evidence about the observed
cases, not prevalence in natural CI traffic.

## Next evidence gate

Before implementing a regression-contradiction shadow, run a second independent wave
and measure:

```text
ground-truth-evaluable rerun failures
CODE_REGRESSION recoveries
CODE_REGRESSION failed-again
UNKNOWN recoveries
UNKNOWN failed-again
test-execution failures vs pre-test failures
JUnit-backed recoveries
cross-repository recurrence
```

Only if independent replication continues to show recoverable test failures
concentrated inside `CODE_REGRESSION` should the project add a read-only
**Historical Regression Contradiction Shadow**.

Even then:

```text
historical contradiction
        !=
retry authority
```

The production gate remains fail-closed.
