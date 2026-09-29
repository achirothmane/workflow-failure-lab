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



## Temporal admissibility

Authorizing use of `eba.integration/v0.1` now follows the versioned
`eba.temporal/v1` profile. The accepted/rejected corpus lives at
`conformance/eba-temporal-v1.json`; cross-owner applicability and exclusions
are documented in `docs/eba-temporal-profile.md`.

The execution boundary receives an explicit evaluation instant. Finite windows
are half-open: `not_before <= now < expires_at`. Exact-expiry reuse fails
closed. AuthorityGrant expiry is finite; malformed time shapes do not degrade to
structural success. A state-bound AssumptionState may use explicit null
wall-clock expiry only when its producing profile has not erased a finite
required dependency.

Historical artifacts remain readable but do not gain these authorization
guarantees retroactively.


## Contextual scope and trust

Authorizing use of the CI profile also follows `eba.context/v1`.

The ActionRequest binds a repository namespace
(`github-repository:<owner/repo>`) and the fixed consumer audience
`workflow-failure-lab/ci-retry-gate`. AssumptionState and AuthorityGrant
must bind the same trace, subject ActionRequest, audience and namespace. The
assumption additionally binds the exact EvidenceBundle reference.

For this CI path the trust mode is explicitly `trusted_in_process`: the
artifacts are constructed and consumed inside the same action process. Their
SHA-256 integrity fields detect mutation; they are **not** external
authentication. A serialized artifact arriving from an untrusted caller must
not become authority merely because it can recompute its own hash.

The Kubernetes/Aegis profile uses a different trust envelope:
`authenticated_parent_binding`. Exact assumption/authority artifact digests,
trace, audience and namespace are covered by the already authenticated signed
execution Permit before the mutation boundary accepts them.

A narrow AssumptionState projection is not a claim that assumption-gate has
executed the full EASL dependency graph. EASL graph evaluation and profile
projection remain distinct semantics.

The accepted/rejected contextual corpus is
`conformance/eba-context-v1.json`.

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


## Assumption-gate integration

The CI Retry Gate profile now emits an explicit `AssumptionState` before the EBA Decision.

The assumption is:

> The failed CI job set bound to this ActionRequest is transient, causally supported, side-effect-safe, and safe to rerun under the current evidence scope.

The Decision contains a real `basis.assumption_refs` entry. At the execution boundary, CI Retry Gate must present the referenced AssumptionState again; the consumer validates:

- `contract_version == eba.integration/v0.1`
- `kind == AssumptionState`
- `status == VALID`
- SHA-256 integrity
- referenced assumption artifact is actually present

A missing, non-VALID, or tampered AssumptionState fails closed.

This integration is contract-based rather than a runtime network call to the separate assumption-gate repository. That preserves reproducibility for GitHub Action consumers and avoids turning a remote repository outage into an authorization ambiguity.


## Agent Action Guard authority integration

The CI Retry Gate profile now produces an explicit `AuthorityGrant` using the
Agent Action Guard authority contract.

The precompiled policy permits the `ci-retry-gate` principal to perform the
`github-actions / rerun_failed_jobs` operation with an explicit side effect.
The resulting grant is narrowed to the exact workflow-run resource from the
ActionRequest.

The EBA Decision now contains a real `basis.authority_ref`.

At the execution boundary the consumer validates:

- contract version and `AuthorityGrant` kind;
- SHA-256 artifact integrity;
- grant is not revoked;
- principal id matches the ActionRequest;
- action id matches the ActionRequest;
- action-scope digest matches actor/tool/operation/resource/side-effect;
- exact resource is inside `resource_scope`;
- requested operation appears in `allowed_actions`;
- environment satisfies `context_constraints`.

A missing, tampered, revoked, or scope-mismatched AuthorityGrant fails closed.

As with assumption-gate, this is a contract-based integration rather than a
runtime network call to the Agent Action Guard repository. The policy profile
is precompiled into the action package so a remote repository outage cannot
silently change authorization behavior.
