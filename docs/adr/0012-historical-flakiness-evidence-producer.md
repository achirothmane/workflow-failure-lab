# ADR-0012: Historical Flakiness Evidence Producer v1

**Status:** Accepted

## Context

Flaky Test Intelligence already collects JUnit observations across workflow history,
detects same-SHA fail-to-pass recoveries, ranks CI waste, and drives advisory
quarantine/triage workflows.

CI Retry Gate answers a different question: whether a rerun is admissible for the
current failed execution.

The missing seam is not another flaky-test dashboard. It is a policy-free evidence
producer that can make historical test behavior available to the retry decision
system without allowing "this test is flaky" to become an automatic rerun rule.

## Decision

Add `historical-flakiness-evidence.ci.v1`.

The producer is invoked by the existing Flaky Test Intelligence path and emits a
machine-readable contract bounded to tests observed failing in the exact analyzed
`run_id + run_attempt`.

For each relevant test it exposes:

- the exact current failure observation;
- collected executions/failures/passes and failure rate;
- same-SHA flips and validated fail-to-pass recoveries;
- persistent-failure revision count;
- evidence from executions other than the exact subject execution;
- failure concentration by JUnit artifact/job name;
- known source-file identities when present.

The producer emits facts only. It does not emit a quarantine recommendation,
`ALLOW`/`BLOCK`, retry limits, or any mutation instruction.

## Temporal boundary

`CaseObservation` v1 does not contain a trusted execution timestamp. Therefore the
producer deliberately calls evidence outside the exact subject execution
`other_execution_evidence`, not `prior_history`.

The contract explicitly sets:

- `history_includes_subject_execution: true`
- `temporal_ordering_proven: false`

A future shadow evaluator must not treat "other execution" evidence as causally prior
until ordering is established from trusted GitHub run/attempt metadata.

## Authorization invariant

Historical flaky-test evidence cannot grant rerun authority in v1.

The production path remains:

```text
CI logs / metadata
        |
        v
Evidence Producer
        |
        v
CI Retry Gate
        |
        +--> ALLOW / BLOCK
```

Historical evidence is an additional read-only producer beside that path:

```text
JUnit history
     |
     v
Historical Flakiness Evidence Producer
     |
     +--> machine-readable evidence
     |
     +--> future shadow comparison
```

It is not wired into `evidence_gate.py` authorization.

## Promotion gate

Production authorization may consume historical flaky evidence only after a shadow
backtest demonstrates, on real failures, that it:

1. reduces `UNKNOWN` decisions by a measurable amount;
2. adds evidence-backed recoveries;
3. does not increase false-positive rerun authorization;
4. preserves fail-closed behavior for persistent failures, contradictory evidence,
   and side-effect boundaries;
5. proves temporal ordering for every historical observation used as prior evidence.

Until those conditions are met, the output is observational only.
