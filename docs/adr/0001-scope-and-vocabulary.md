# ADR-0001: Scope and Certainty Vocabulary

- Status: Accepted
- Date: 2026-07-18
- Deciders: Project owner (vocabulary origin), principal engineer (recording only)

## Context

Workflow Failure Lab analyzes failed workflow executions and must express how certain a conclusion is. Getting this vocabulary wrong — or letting it drift — is exactly the failure mode the tool exists to prevent: optimistic conclusions and blind retries against external systems.

The certainty vocabulary is **imported from a specification owned by the project owner** (recorded in `docs/problem-statement.md`). This ADR records it; it does not derive it. No module, document, or future ADR may re-derive these terms, rename them, add synonyms, or shift their meaning. Changing them requires a new ADR approved by the project owner that supersedes this one.

## Decision

### Vocabulary (imported, fixed)

| Term | Meaning (verbatim from owner's specification) |
|---|---|
| `SUCCEEDED` | The execution completed with enough evidence of success. |
| `FAILED_CONFIRMED` | The execution failed and the failure is confirmed. |
| `INDETERMINATE` | The available data cannot prove success or confirmed failure. |

These are the only three certainty values. There is no fourth state, no "UNKNOWN", no "PARTIAL", no severity levels attached to them.

### Binding rules

1. **Retry rule:** Retry is permitted **if and only if** the previous attempt is `FAILED_CONFIRMED`.
2. **Reconciliation rule:** `INDETERMINATE` requires reconciliation — checking the external system before attempting the action again. **Blind retry is forbidden** when the result is `INDETERMINATE`.

Corollaries that follow directly (not new rules): `SUCCEEDED` never leads to a retry; `INDETERMINATE` never leads to a retry without reconciliation first.

### Evidence rule

An analysis may claim a classification only when the input evidence supports it. Missing or ambiguous evidence must classify as `INDETERMINATE`, never as an optimistic `SUCCEEDED` or a pessimistic `FAILED_CONFIRMED`.

## Consequences

- The `domain` module encodes exactly these three values (as an enum) and nothing else; all other modules consume it.
- The reporting output prints the terms verbatim — no translation, abbreviation, or restyling.
- Raw source-system statuses (whatever strings appear in input JSON) are data, not vocabulary; mapping them onto these three terms is `analysis`'s job and must follow the evidence rule.
- Any perceived gap in the vocabulary is recorded below as a proposal, not implemented.

## Observed gaps — proposals only (no change to vocabulary or rules)

Recorded per the mandate to log gaps without altering the specification:

1. **Reconciliation outcome is unnamed.** After reconciliation, the result presumably becomes `SUCCEEDED` or `FAILED_CONFIRMED`, but the specification does not name the state "reconciliation performed, still unprovable". Proposal for the owner: clarify whether repeated `INDETERMINATE` after reconciliation stays `INDETERMINATE` indefinitely (current reading: yes).
2. **Per-step vs. per-execution certainty.** The vocabulary is defined for an execution; steps carry raw statuses. Proposal for the owner: confirm whether the same three terms may also classify individual steps, or whether step-level certainty stays out of vocabulary.
3. **Retry-count bounds are unspecified.** The retry rule permits retry after `FAILED_CONFIRMED` with no stated limit. Proposal for the owner: state whether bounding retries is policy for a later version or intentionally out of scope.

These proposals await the owner's decision; until then the vocabulary and rules above apply exactly as written.
