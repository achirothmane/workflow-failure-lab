# ADR-0005: CI Retry Gate consumes EvidenceBundle only

**Status:** Accepted

## Context

ADR-0004 introduced a policy-free Evidence Producer, but the retry gate still read `JobAssessment` objects directly. That left a hidden coupling between the producer internals and authorization logic.

A real evidence-gated architecture needs an explicit serialization boundary:

    raw logs / metadata
            |
            v
    Evidence Producer
            |
            v
    EvidenceBundle
            |
            v
    CI Retry Gate
            |
            v
    ALLOW / BLOCK

The gate must be able to make its evidence decision without access to raw logs, `JobAssessment`, parser internals, or source-system objects.

## Decision

The CI Retry Gate now accepts the canonical `evidence-producer.ci.v1` bundle as its only evidence input.

The gate reads deterministic claims from `derived`:

- `failure_category`
- `classification_confidence`
- `execution_provenance_status`
- `side_effect_risk`

Retry limits remain a separate execution-policy input.

The orchestration layer may still keep `JobAssessment` objects for human reports and diagnostics, but it must produce the bundle before calling the authorization gate.

## Fail-closed rules

- unsupported or malformed bundle -> BLOCK
- no failed-job claims -> BLOCK
- missing required claims -> BLOCK
- conflicting duplicate claims -> BLOCK
- side-effect risk -> BLOCK
- non-transient or low-confidence classification -> BLOCK
- unconfirmed execution provenance -> BLOCK
- exhausted retry policy -> BLOCK

## Consequences

The dependency direction is now explicit:

    JobAssessment -> Evidence Producer -> EvidenceBundle -> Retry Gate

There is no reverse dependency from the gate to `JobAssessment`.

This makes Evidence Producer independently reusable by future consumers such as CI reliability controls, MCP action gates, or agent-action authorization systems.
