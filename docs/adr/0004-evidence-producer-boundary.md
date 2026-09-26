# ADR-0004: Evidence Producer boundary

**Status:** Accepted

## Context

The retry gate already collects logs, execution provenance, failed-step provenance,
side-effect signals and deterministic failure classifications. Its machine-readable
output also contains the authorization result (ALLOW/BLOCK) and execution policy.

That is useful operationally, but it leaves two different responsibilities in one
artifact:

1. What was observed or deterministically derived from the failed execution?
2. Given those facts and a policy, is a rerun allowed?

If those responsibilities remain coupled, later consumers (CI reliability,
agent-action gates, MCP tools, or other execution systems) cannot reuse the evidence
without also inheriting retry-specific policy.

## Decision

Introduce a separate **Evidence Producer** contract before the retry gate.

The producer emits `evidence-producer.ci.v1` with four explicit layers:

- `observations`: source facts extracted from CI logs/metadata.
- `derived`: deterministic claims computed from those facts.
- `inferred`: reserved for non-deterministic/model inference; empty in v1.
- `quality`: missing sources and structural contradictions.

The producer is intentionally **policy-free**. It must not emit ALLOW/BLOCK, retry
limits, or trigger an action.

The CI Retry Gate remains the first consumer. In this first extraction step the
existing gate behavior is unchanged; its decision payload embeds the producer bundle
while authorization logic still consumes the existing assessments directly.

## Invariants

- Observation is never relabeled as inference or vice versa.
- Missing evidence remains explicit.
- A producer may report evidence quality, but not action authorization.
- Retry policy stays outside the evidence bundle.
- V1 is deterministic; AI/model interpretation cannot silently become a fact.

## Consequences

This creates a stable seam for the next refactor:

```text
CI logs / metadata
        |
        v
Evidence Producer
        |
        v
Evidence Bundle
        |
        v
CI Retry Gate
        |
        +--> ALLOW / BLOCK
```

Once the bundle contract is proven by CI fixtures, the gate can be migrated to
consume the bundle as its sole evidence input. Other producers can later target the
same conceptual contract without being forced to adopt CI retry policy.
