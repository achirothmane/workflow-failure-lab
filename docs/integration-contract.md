# Evidence-before-Action Integration Contract v0.1

Status: implementation candidate  
Contract version: `eba.integration/v0.1`

## Purpose

This contract is the interoperability boundary between Evidence-before-Action components. It does not replace CI Retry Gate's existing evidence policy. It wraps that policy in stable artifacts that can later be consumed by EASL, assumption-gate, Agent Action Guard / Aegis-EGE, State Latch, and token-governance-protocol.

The invariant is:

> No action executes unless a current Decision artifact authorizes the exact ActionRequest presented at the execution boundary.

## Canonical flow

```text
ActionRequest
  -> Evidence
  -> Assumption / state validation
  -> Authority / resource gates when applicable
  -> Decision(ALLOW | BLOCK)
  -> exact-action binding check
  -> Execution
  -> ExecutionReceipt
  -> new evidence
```

## Common fields

Every contract artifact carries:

- `contract_version`
- `kind`
- `id`
- `trace_id`
- `producer`
- `created_at`
- `integrity.algorithm`
- `integrity.digest`

Artifacts are immutable. A material change creates a new artifact.

## ActionRequest

An ActionRequest identifies the principal, requested action, target resource and execution context. For the CI Retry Gate profile, the context binds:

- repository
- workflow run id
- run attempt
- head SHA
- workflow id

The action digest is calculated from principal + action + context. Changing any bound value invalidates a prior authorization.

## Decision

A Decision is the only artifact that authorizes execution.

Required decision values:

- `ALLOW`
- `BLOCK`

There is no implicit authorization state.

The CI profile preserves the existing evidence decision as its policy source:

`ci-retry-gate.evidence-decision.v1`

and references the canonical EvidenceBundle by SHA-256.

## Execution boundary

Immediately before calling GitHub's rerun endpoint, CI Retry Gate MUST have:

1. an existing evidence-gate `ALLOW`;
2. successful EASL subject-binding revalidation;
3. an EBA Decision whose `request_ref` matches the ActionRequest;
4. an EBA Decision whose `action_digest` matches the current ActionRequest.

A mismatch fails closed.

## ExecutionReceipt

A receipt is emitted for the final result of the gate invocation.

For the current CI profile:

- `SUCCEEDED` means the GitHub rerun request was dispatched and accepted by the API call;
- `NOT_EXECUTED` means no rerun API call was attempted.

It does **not** claim that the later CI rerun itself passed. That later workflow outcome is separate evidence and can feed the next decision.

## CI profile versus full contract

CI Retry Gate does not currently require a token budget or a separate delegated-authority service, so those Decision basis fields are null/empty in this profile.

That is intentional. The integration contract standardizes the slots without pretending that every primitive is already active in every execution profile.

Future Aegis-EGE profiles can require:

- `assumption_refs`
- `authority_ref`
- `budget_ref`
- `approval_refs`

and fail closed when a required slot is absent.

## Hard invariants

1. No ALLOW -> no execution.
2. Decision applies only to the exact action digest.
3. Unknown or missing required state fails closed.
4. Material context change invalidates authorization.
5. Evidence and contract artifacts are integrity-bound.
6. Receipt -> Decision -> ActionRequest -> Evidence must remain traceable.
7. A successful dispatch receipt is not proof of successful downstream execution.

## First implementation

The first proving ground is CI Retry Gate because it already contains:

- deterministic EvidenceBundle production;
- canonical evidence hashing;
- isolated `ALLOW/BLOCK` evaluation;
- EASL-style subject binding before rerun;
- a real side effect: GitHub failed-job rerun.

This makes it the smallest real end-to-end Evidence-before-Action integration surface.
