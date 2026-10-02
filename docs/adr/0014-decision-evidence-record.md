# ADR-0014: Decision Evidence Record as the CI retry audit primitive

**Status:** Accepted

## Context

CI Retry Gate already produces a canonical policy-free EvidenceBundle, verifies its
SHA-256 digest before authorization, emits an ALLOW/BLOCK evidence decision, binds
authorization to exact workflow state, and emits an Evidence-before-Action
ExecutionReceipt.

Those primitives answer different questions:

- EvidenceBundle: what was observed and derived?
- Evidence decision: is the current evidence sufficient to authorize retry?
- ExecutionReceipt: was the authorized effect request accepted?

What is missing is one immutable, product-facing audit record that binds the final
decision to the evidence digest, policy, authority path, subject state, and actor
identities at decision time.

A mutable log entry is not sufficient. Outcome arrives later than the decision and
must not be written back into the same record.

## Decision

Introduce a first-class **Decision Evidence Record (DER)** with schema:

`ci-retry-gate.decision-record.v1`

Every final ALLOW or BLOCK decision produces one DER before an optional retry
mutation.

The DER contains, at minimum:

- an event ID and recorded-at timestamp;
- the exact repository/workflow run/attempt/head/workflow subject;
- `decision: ALLOW | BLOCK`;
- evidence status and the first human-readable reason;
- `evidence_bundle_sha256`;
- `policy_ref`;
- `authorization_path: POLICY | HUMAN_OVERRIDE`;
- `next_action`;
- typed raw identities;
- optional parent-decision linkage;
- `record_sha256`.

`record_sha256` is SHA-256 over canonical JSON with the top-level
`record_sha256` field omitted. This avoids a self-referential digest while making
the semantic record deterministic.

A reader must verify the embedded digest before use. When an expected digest is
available from an external anchor, it must also match or the record is rejected.

## Identity model

Do not normalize every principal to a username. Preserve raw identity and classify
only when supported by evidence.

Allowed v1 types:

- `human`
- `github_app`
- `token`
- `bot`
- `unknown`

The schema can represent:

- `workflow_actor`
- `decision_engine`
- `rerun_initiator`
- `override_requester`
- `override_approver`

Missing identities remain absent rather than guessed.

## Override semantics

`OVERRIDE` is not a decision value.

An override that authorizes an effect is represented as:

```
decision: ALLOW
authorization_path: HUMAN_OVERRIDE
```

The v1 schema requires an override actor and a non-empty reason. Two-person
approval is not mandatory in v1; it can become a policy option later without a
schema break.

## Temporal separation

Decision and outcome are separate immutable facts.

```
EvidenceBundle
    -> Decision Evidence Record
    -> optional ExecutionReceipt
    -> later OutcomeRecord
    -> later ReconciliationRecord
```

The DER never receives a later `final_result` field.

A later attempt may verify the prior DER, bind it to the same workflow run and head
state, and create a separate outcome/reconciliation record. A missing later attempt
means only `NO_SUBSEQUENT_ATTEMPT_OBSERVED`; it does not prove a prior BLOCK was
counterfactually correct.

## Parent linkage

A DER may contain one `parent_decision` reference:

- `event_id`
- `record_sha256`
- `run_attempt`

This is linkage, not authorization inheritance. A previous DER can never authorize a
new attempt. Fresh evidence and fresh admission are always required.

## Runtime placement

The DER is created only after conservative outer guards and state checks have
narrowed the decision, and before any optional rerun mutation.

The production effect boundary must never consume the DER as a substitute for the
existing evidence/authority contract. The DER is an audit artifact, not a new source
of authority.

## Storage

The free Action may upload DER JSON through GitHub Actions artifacts. This gives a
server-side immutable artifact object for the retention period but does **not** give
cryptographic non-repudiation.

Known limitations:

- repository deletion can remove repository-scoped evidence;
- Actions retention is bounded by repository/organization policy;
- a SHA-256 digest proves integrity only relative to a trusted digest anchor;
- repository-local storage is not an independent compliance archive.

These are explicit product constraints, not claims of tamper-proof storage.

A future external store may add longer retention, organization-wide query,
attestation/signatures, and storage outside the repository failure domain only after
demand is demonstrated.

## Product language

Internal name: **Decision Evidence Record (DER)**.

User-facing language should prefer **audit trail** or **decision log**.

## v1 acceptance criteria

1. Every ALLOW/BLOCK can produce a sealed DER with canonical `record_sha256`.
2. Reading a DER verifies its embedded digest and an external expected digest when
   supplied.
3. DER includes `evidence_bundle_sha256`, `policy_ref`,
   `authorization_path`, and `next_action`; it contains no outcome and no raw
   logs.
4. Identities preserve raw value plus type. Human override requires a reason.
5. A three-attempt synthetic chain verifies A -> B -> C parent linkage without
   inheriting authority.
6. One-byte/semantic corruption causes digest verification to fail before the
   record is trusted.

## Non-goals for this slice

This ADR does not introduce:

- a hosted fleet service;
- hidden telemetry;
- a claim that GitHub artifacts are non-repudiable;
- a new retry classifier;
- a new production authorization path;
- mandatory two-person override;
- outcome polling or webhooks.

Cross-attempt artifact discovery and Outcome/Reconciliation records are the next
runtime slice after the DER write/read contract is proven.
