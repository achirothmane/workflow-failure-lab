# ADR-0015: Next-attempt audit chain and reconciliation

**Status:** Accepted

## Context

ADR-0014 introduced the immutable Decision Evidence Record (DER) at decision time
T1. The next missing link is T2: when the same GitHub Actions workflow run reaches
attempt N+1, the gate should be able to observe what happened after the prior
decision without polling, webhooks, or a hosted service.

The prior record is historical evidence only. It must never authorize the current
attempt.

## Decision

For the normal current-attempt path, attempt N+1 may discover the GitHub Actions
artifact produced for attempt N.

The artifact name is:

```
ci-retry-gate-der-{workflow_run_id}-attempt-{N}-{decision_record_sha256}
```

The full DER digest is retained in the artifact name as a repository-side digest
anchor. Older 12-character anchors remain readable during migration, but new
artifacts use the full digest.

The uploaded audit artifact contains:

- the DER;
- the EBA ExecutionReceipt;
- when available, the OutcomeRecord and ReconciliationRecord created for the
  previous attempt.

## Discovery semantics

The reader lists repository Actions artifacts and matches the exact run/attempt
prefix.

- zero matches: prior audit history is unavailable;
- one non-expired match: download and verify it;
- more than one match: history is ambiguous and no parent is selected.

The reader never resolves ambiguity by "latest", completion order, or artifact ID.

History failure is non-authorizing. Discovery failure, retention expiry, malformed
ZIP, digest mismatch, or binding mismatch cannot turn a current BLOCK into ALLOW
and cannot turn a current ALLOW into BLOCK by itself. The current attempt is always
evaluated from fresh evidence.

## Verification

Before a prior DER is trusted:

1. verify its embedded canonical SHA-256;
2. compare the digest to the artifact-name anchor;
3. verify the optional EBA ExecutionReceipt integrity;
4. bind repository, workflow run ID, workflow ID, head SHA, and
   `current_attempt == parent_attempt + 1`.

Only a verified and bound DER may become `parent_decision` linkage in the new
DER.

Parent linkage is history, not authority inheritance.

## OutcomeRecord

A verified parent may produce:

`ci-retry-gate.outcome-record.v1`

The record contains no raw logs. It records:

- parent decision event ID and digest;
- optional parent ExecutionReceipt digest;
- exact run/attempt/head/workflow subject;
- observed workflow status/conclusion;
- previous failed job identities;
- recovered, recurrent, unmatched, and currently failed job identities;
- effect attribution.

Effect attribution is:

- `GATE_DISPATCH_CONFIRMED` only when the retained prior ExecutionReceipt says
  the gate's rerun dispatch was accepted;
- otherwise `EXTERNAL_OR_UNKNOWN`.

## ReconciliationRecord

A verified outcome may produce:

`ci-retry-gate.reconciliation-record.v1`

Possible v1 statuses include:

- `RECOVERED_AFTER_RERUN`
- `RECURRENT_FAILURE`
- `PARTIAL_RECOVERY`
- `OUTCOME_UNKNOWN`
- `SUBSEQUENT_ATTEMPT_EXTERNAL_OR_UNKNOWN`
- `SUBSEQUENT_ATTEMPT_AFTER_BLOCK`

A later attempt after BLOCK does not prove the BLOCK was incorrect. It records only
that another authority path or external rerun may have occurred.

## Storage and failure domain

GitHub Actions artifacts remain repository-scoped evidence. Repository deletion,
retention expiry, or authorized artifact deletion can remove them. This slice does
not claim non-repudiation or independent archival.

A future external organization/fleet store can address that failure domain only
after usage evidence supports the product need.

## Non-goals

This slice does not add:

- polling or webhooks;
- hosted storage;
- hidden telemetry;
- a new classifier;
- a new production override path;
- authority inherited from a previous attempt;
- a claim that ALLOW/BLOCK was counterfactually "correct".
