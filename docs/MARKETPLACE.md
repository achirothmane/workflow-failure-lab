# Marketplace submission copy

## Proposed title

Protect n8n lead enrichment releases with measured canaries and automatic rollback

## Short description

Roll out a new read-only n8n workflow gradually, validate its business output, compare errors and latency against Stable, and fall back safely when a Candidate regresses.

## Who this is for

Automation engineers and agencies operating business-critical n8n enrichment, classification, extraction, or scoring workflows. A read-only processing step must complete before the caller writes to CRM or performs another irreversible operation.

## What it does

ReleaseGuard keeps a frozen Stable workflow while Candidate receives 5%, 25%, 50%, then 100% of protected requests. It measures actual upstream errors and p95 latency, validates JSON Schema and cross-field business invariants, and makes deterministic PROMOTE / HOLD / ROLLBACK decisions.

A Candidate can return HTTP 200 and still fail validation. ReleaseGuard preserves that failure as evidence, routes future traffic to Stable, and uses a verified read-only fallback for the current request. It refuses promotion when samples, confidence, dwell time, or observations are insufficient.

Decisions, routing revisions, and policy/config hashes are recorded with a verifiable local audit chain. A transactional outbox delivers HOLD and ROLLBACK alerts with reason codes and retryable event IDs.

## Setup and dependencies

1. Deploy the open-source ReleaseGuard service with PostgreSQL.
2. Import Gateway, Stable, Candidate, and alert receiver JSON.
3. Bind Header Auth credentials and publish the workflows.
4. Configure the release, output/business contract, and thresholds.
5. Run the Setup Doctor and route protected requests through Gateway.
6. Add your alert destination and inspect the fault demonstration.

Requires Node 22 or Docker, PostgreSQL 16, and a synchronous read-only JSON workflow. This is a workflow + companion service product; the JSON alone does not provide transactional rollout safety. The demonstrated n8n version is 2.41.4; other versions and n8n Cloud require their own compatibility validation.

## Why source control and backups remain useful

Source control and history manage workflow artifacts. ReleaseGuard evaluates observed behavior while new requests are flowing and limits a regression's exposure. Keep your normal backup/versioning process.

## Honest limitations

- Read-only synchronous workflows only in v0.1.
- One ReleaseGuard service process per database; no HA promise.
- Does not undo business writes already executed.
- Requires immutable published workflows during each release.
- JSON Schema checks only the explicitly declared invariants; it does not establish truth of arbitrary AI answers.
- Stable probes consume additional executions.
- A local audit hash chain needs an external anchored head to resist a privileged database rewrite.
- The included receiver formats alerts; bind a destination for operational notification.
- No automatic archival policy or sustained load certification in this version.

## Evidence supplied

- Actual imported n8n gateway canvas.
- Actual automatic-rollback dashboard after an intentionally broken Candidate.
- Actual completed progressive rollout dashboard.
- Machine-readable adversarial HTTP/PostgreSQL and real n8n results.
- Exact tested commit and SHA-256 file manifest.

Use the generated screenshots only when the corresponding test run succeeded. Do not replace failures with synthetic success screenshots. Review the current Creator Hub criteria at submission time; this copy is prepared for submission, not a guarantee of acceptance.
