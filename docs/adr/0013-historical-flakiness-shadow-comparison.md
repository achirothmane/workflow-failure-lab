# ADR-0013: Historical Flakiness Shadow Comparison v1

**Status:** Accepted

## Context

PR #103 introduced a policy-free historical flaky-test evidence producer. The next
question is whether that evidence can improve retry decisions without weakening the
production gate.

A naive implementation could leak future outcomes into a retrospective analysis or
treat a historical flake rate as sufficient rerun authority. Both would invalidate
the experiment.

## Decision

Add a read-only shadow comparison beside the production retry decision.

The shadow evaluator runs only when the production baseline is:

- decision = BLOCK
- evidence_status = UNKNOWN

It evaluates only tests observed failing in the exact subject run attempt.

Historical observations may contribute only when they are proven strictly earlier
than the subject execution:

- earlier attempts of the same GitHub run are ordered by run_attempt;
- different runs require trusted GitHub execution timestamps;
- missing or equal cross-run timestamps produce ORDERING_UNAVAILABLE.

The first support threshold is deliberately conservative:

- at least two prior same-SHA fail-to-pass recoveries;
- zero prior persistent-failure revisions.

A persistent historical failure is reported as HISTORICAL_CONTRADICTION.

## Safety invariant

The shadow evaluator cannot change retry authorization.

Every result contains:

authorization.changed = false

The production evidence gate remains authoritative and is not modified by this ADR.

Historical support does not resolve missing execution provenance, side-effect risk,
deterministic regression evidence, retry limits, or other gate requirements.

## Anti-leakage invariant

Future observations must never contribute to shadow support.

This is tested explicitly. If temporal ordering cannot be established, the evaluator
fails closed with ORDERING_UNAVAILABLE.

## Outputs

The composite action exposes:

- historical-flakiness-shadow-json
- historical-flakiness-shadow-status
- historical-flakiness-shadow-supported-tests
- historical-flakiness-shadow-contradictions

These are observability and experiment outputs only.

## Next promotion gate

Historical evidence may influence production authorization only after retrospective
ground-truth evaluation demonstrates measurable coverage improvement with no increase
in false-positive rerun authorization.
