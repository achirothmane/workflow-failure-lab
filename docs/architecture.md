# ReleaseGuard implementation

## Request path

Gateway validates the input and logical request ID, then calls the authenticated service. The service checks the declared input contract before upstream execution. Bad input returns 400 and is excluded from regression observations. Compiled validators are cached by canonical schema with a fixed cap. The service reserves the request and route under a PostgreSQL row lock, then rechecks the admission revision before dispatch. Stable/Candidate production webhooks return a version-marked result. The service measures the actual HTTP call and validates the result contract.

An invalid/error Candidate outcome is settled before evaluation or fallback. The original observation never becomes a Stable success. A verified read-only fallback is a separate attempt and is excluded from baseline promotion metrics. This avoids selecting only failed Candidate cases as the Stable comparator.

Successful responses are encrypted with AES-256-GCM in the request ledger. Exact retries replay that validated response. Concurrent duplicates return 409 instead of running twice. No raw input payload is stored; its canonical HMAC fingerprint binds the request ID to the payload. The same persistent key also derives private deterministic rollout buckets.

## Decision path

An evaluator runs every five seconds. Measurements are separated by release, arm, and stage epoch. It computes exact observed counts and PostgreSQL percentile_disc p95, without a truncated sample becoming the denominator.

The pure decision function first handles invalid state/metrics, observed bad Candidate outcomes, and bad Stable. It then applies completeness/freshness, minimum samples, absolute/relative error/latency limits, Wilson bounds, dwell, in-flight drain, and fresh confirmation batches.

Updating the stage/stop state, incrementing the revision, appending the evidence record, and queuing alert delivery share one transaction. Concurrent evaluators serialize on the same release row; only one can consume an eligible epoch's evidence and advance.

Every admission reads persisted state. If the evaluator lease expires, Candidate traffic stops. A reserved old ticket must pass a dispatch fence; after rollback its old revision cannot authorize a new Candidate dispatch.

## Rollback failures

Rollback changes service routing. It does not issue a separate n8n deployment API mutation. This removes one common source of “rollback requested but the old Candidate is still accepting new ingress” uncertainty.

The remaining fault is a failed/delayed PostgreSQL commit. When a safety decision is made, an admission pause is raised before its state mutation, so new Candidate tickets cannot cross the commit-confirmation window. Undispatched revoked tickets are retained as cancelled and excluded from observations. The service marks an in-memory safety fence immediately on an operator stop and on evaluator/state failures, aborts its in-flight Candidate fetches, and denies subsequent requests until a confirmed operator rollback resolves the incident.

v0.1 enforces a single controller via a dedicated PostgreSQL advisory-lock connection. A second process is rejected. This makes the scope of a local emergency fence explicit. In-flight n8n work already admitted can continue despite an HTTP abort; read-only scope is therefore essential. Distributed fencing/HA are future engineering work.

On restart, the service evaluates persisted active releases before listening. Pending lost observations age into incomplete evidence rather than successes. Unknown requests return 409; operators use a new release after correcting the cause.

## Evidence and alerts

Records bind the policy/config hash, decision/reason, metrics, prior/next state, stage epoch, and routing revision. A canonical SHA-256 chain is verifiable against its stored head. It is locally tamper-evident relative to that head; a privileged full rewrite requires an independently preserved head to detect.

Alert delivery uses an outbox in the state transaction. Retries use a bounded backoff and preserve eventId. The destination owns idempotent deduplication and human notification.

## Compatibility boundaries

This implementation targets actual published production webhooks in n8n 2.41.4, with Header Auth and JSON responses. It does not assume n8n's internal database schema. A small PostgreSQL product schema stores rollout state; n8n keeps its own database and credentials.

Synchronous JSON, one fixed allowlisted upstream origin, read-only arms, frozen published versions, and a single controller are v0.1 constraints. The business contract is explicit operator configuration, not model judgment or a universal workflow validator.
