# ADR-0006: EvidenceBundle is a runtime artifact

**Status:** Accepted

## Context

ADR-0004 separated evidence production from policy in the data model. ADR-0005 made
the CI Retry Gate consume EvidenceBundle rather than JobAssessment objects.

The remaining coupling was runtime coupling: producer and gate still executed in the
same Python process and shared the in-memory bundle.

That makes the boundary easy to bypass accidentally and gives no transportable
artifact for replay, audit, or an independent future consumer.

## Decision

Persist every produced CI EvidenceBundle as canonical JSON before authorization.

The producer writes an `*.evidence.json` file and computes SHA-256 over canonical
JSON bytes. The authorization gate runs as a separate Python process and receives
only:

- the evidence artifact path,
- its expected SHA-256 digest,
- execution policy such as `max_attempts`.

The gate re-reads and verifies the artifact before evaluating it. A digest mismatch,
invalid JSON, unsupported evidence shape, or gate runtime error fails closed.

The main orchestrator no longer imports `evidence_gate`.

## Runtime boundary

    GitHub API / logs
          |
          v
    Evidence Producer
          |
          v
    canonical evidence.json + SHA-256
          |
          | process boundary
          v
    evidence_gate_cli.py
          |
          v
    ALLOW / BLOCK decision JSON

Recovery and recurrence checks remain conservative outer guards: they may turn an
ALLOW into BLOCK, but they cannot create authorization.

## Consequences

The evidence artifact can now be:

- retained for audit,
- replayed through the gate,
- transported to another process or job,
- integrity-checked before authorization,
- consumed later by a different evidence gate.

The GitHub Action exposes both the artifact path and SHA-256 digest.
