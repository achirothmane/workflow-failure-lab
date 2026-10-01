# Executed validation

The primary evidence is the exact-head GitHub Actions run plus evidence/adversarial-results.json, evidence/n8n-e2e-results.json, screenshots, and evidence/build-manifest.json in its downloaded package. An unsuccessful run remains an unsuccessful run; packaging does not make a build ready.

## Layers

| Layer | Method | What it establishes |
|---|---|---|
| Policy/security | Node built-in test runner | Deterministic decisions, bounds, validation, tokens, replay encryption, and traffic bucketing |
| Storage/orchestration | Actual Node HTTP server + PostgreSQL | Real transactions, concurrent evaluators/requests, fence timing, rejected rollback commits, failure/latency/output handling |
| n8n compatibility | Real n8n 2.41.4 in Docker | Import, credential binding, publication, production webhook behavior, Gateway → sidecar → Candidate → Stable fallback |
| Browser evidence | Playwright Chromium | Actual dashboard state/audit integrity and imported n8n canvas |

The first 25 policy cases were also executed in the conversation's JavaScript runtime. The full Node/HTTP/PostgreSQL and n8n suites run on GitHub, not that limited runtime.

## Required adversarial coverage

| User case | Test and expected result |
|---|---|
| Bad incoming input | Invalid payload → 400 before upstream execution; no Candidate regression sample |
| Candidate raises errors | Real HTTP full failures, early error threshold and absolute failure budget → ROLLBACK |
| Candidate raises latency | Actual delayed upstream and relative/absolute p95 tests → ROLLBACK |
| Candidate output invalid | HTTP 200 + wrong field type → ROLLBACK and validated Stable fallback |
| Candidate partially fails | 25% selected-request failures retained even when fallback succeeds → ROLLBACK |
| Incomplete metrics | Real PostgreSQL observations with NULL latency → HOLD + PAUSED |
| Insufficient sample | Small valid sample → HOLD, current percentage, no PROMOTE |
| Stable fails | Bad Stable evidence / actual n8n Stable error → HOLD, no opportunistic promotion |
| Rollback fails | PostgreSQL trigger rejects update → no successful rollback claim; local admission denied |
| Rollback delayed | PostgreSQL row lock delays commit → admission denied immediately, confirmed state after commit |
| Plausible but semantically inconsistent output | Declared cross-field priority/score invariant → reject and rollback |
| Concurrent evaluators | Eight concurrent evaluations on one eligible epoch → exactly one stage advancement |
| Safety commit window | Admission pause is raised before a rollback/safety mutation; cancelled tickets are not false successes |
| Old ticket | Reserved Candidate ticket after rollback → dispatch fence denies it |
| Duplicate request | Same logical request concurrently / replayed → one execution, encrypted response replay |
| Lease expires | Expired admission lease → Stable routing |
| 100% evidence | Real Stable control probes retained at full Candidate traffic |
| Regression after completion | Invalid new Candidate output → rollback to retained Stable |
| Audit tampering | Canonical chain verification includes policy/config and routing revisions |
| Alert receiver unavailable | Durable outbox retains and schedules failed delivery |

## Accelerated policy

Integration tests accelerate dwell and some sample/confidence thresholds to exercise transitions quickly. Production defaults remain in src/policy.mjs and config/demo-release.json. The real n8n healthy-stage demonstration uses 20 samples per arm and a one-batch test policy. Strict default sample/confidence/dwell behavior is tested separately.

The PostgreSQL healthy-stage test seeds known observations to isolate atomic advancement. The n8n healthy-stage test obtains observations from actual n8n executions. These are different forms of evidence and are labeled separately.

## Limits of this evidence

No sustained throughput, multi-day soak, database failover, multi-process HA, real customer workflow, n8n Cloud compatibility, external Slack/email delivery, or paid adoption is proven by these tests. Output checks prove only the specified contract. A local chain does not defend against a privileged rewrite of its entire history/head.

Screenshots are generated only after the real n8n functional cases succeed. Preserve failures and fix the cause; do not weaken CI checks to obtain green results.

The real integration exposed a startup distinction in n8n 2.41.4: `/healthz` can return 200 before published webhooks are registered. The harness now waits on `/healthz/readiness`, which the n8n implementation marks only after initialization completes. This was fixed instead of retrying arbitrary failed business requests.

The live n8n run also rejected literal string response codes in the exported Respond to Webhook nodes. The exports now use integer 200, and import checks guard that type. The dynamic Gateway response expression remains numeric.
