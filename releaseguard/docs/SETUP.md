# ReleaseGuard setup guide

## 1. Choose an eligible workflow

Choose a synchronous JSON transformation that does not send emails, charge money, create records, or mutate remote state. Examples: prepare a lead score, enrich data through read-only lookups, classify incoming requests, or extract structured document fields.

Keep the business write in the caller **after** a validated response. ReleaseGuard's retry and rollback operate on the read-only preparation step. A read-only declaration is an operator responsibility, not a proof that arbitrary n8n nodes have no side effects.

## 2. Start the private demo stack

The provided stack binds the two HTTP ports to localhost. This is a local setup, not a public TLS deployment.

~~~sh
node scripts/generate-env.mjs
docker compose up -d --build
~~~

Keep .env and both persistent volumes. RESPONSE_KEY_HEX decrypts cached replies and fixes cohorts/fingerprints; do not rotate it casually. N8N_ENCRYPTION_KEY protects n8n credentials. Back up these keys together with their respective databases.

Open http://127.0.0.1:5678 and create the n8n owner. No paid n8n plan is required for the demonstrated webhook approach. Source control features are complementary and separate.

## 3. Import workflows and bind credentials

Import each file through n8n's Import from File menu. The exported files contain no credentials or pinned payloads.

| Workflow / node | Credential type | Header name | Header value |
|---|---|---|---|
| Stable / Incoming request | Header Auth | x-releaseguard-upstream | UPSTREAM_TOKEN |
| Candidate / Incoming request | Header Auth | x-releaseguard-upstream | UPSTREAM_TOKEN |
| Gateway / Receive lead | Header Auth | x-releaseguard-client | CLIENT_TOKEN |
| Gateway / Execute guarded release | Header Auth | Authorization | Bearer DATA_TOKEN |
| Alerts / Receive decision alert | Header Auth | x-releaseguard-alert | ALERT_TOKEN |

Create credentials in n8n; copy the corresponding values from your local .env without putting them in workflow JSON. In the HTTP Request node choose generic Header Auth. In each Webhook choose Header Auth.

Publish Stable, Candidate, Alerts, and Gateway. Wait for n8n's /healthz/readiness to return 200; /healthz alone reports process liveness before webhook registration is complete. The CLI is also available for self-hosted administration: publish:workflow --id=<id>; a running instance must restart after CLI publication. The CI harness tests this path in an isolated instance.

## 4. Register the release

The bundled config points the service at the Compose n8n service. For an existing instance, update Stable/Candidate URLs and set ALLOWED_UPSTREAM_ORIGIN to that exact origin in the service environment. Only production /webhook/ paths are accepted; redirects, credential-bearing URLs, and arbitrary destinations are rejected.

Adjust Gateway's guardBase and releaseId. Adjust config/demo-release.json's inputSchema and outputSchema to your real input/output. Input validation runs before upstream execution; malformed requests return 400 and cannot pollute Candidate regression metrics. Stable and Candidate return:

~~~json
{
  "releaseguardVersion": "candidate-v1",
  "result": {"leadId": "L-42", "score": 81, "priority": "HIGH", "engine": "candidate"}
}
~~~

~~~sh
npm ci
node --env-file=.env scripts/register.mjs config/demo-release.json
node --env-file=.env scripts/doctor.mjs config/demo-release.json
~~~

The Doctor executes read-only smoke requests. Customize its payload before using it with your own business contract. READY_FOR_CANARY means setup checks passed; it does not waive sample or confidence gates.

## 5. Send traffic

POST to http://127.0.0.1:5678/webhook/releaseguard with:
- Content-Type: application/json
- x-releaseguard-client: CLIENT_TOKEN
- x-request-id: a unique ID for each logical request; reuse it for retries of exactly the same payload.

Body: {"leadId":"L-42","score":81}. Successful output includes servedBy, fallback, requestId, releaseId, and result. HTTP 503 indicates no valid result or unavailable release state. An in-progress duplicate returns 409; wait and retry the same ID after the first response. A changed payload under an existing ID returns 409.

## 6. Operate

Open http://127.0.0.1:8080. The admin token stays in the current page memory; it is not written to browser storage. Review p95, raw Candidate failures, completeness, rollout stages, and audit integrity.

The service evaluates every five seconds, renews a 30-second admission lease, and drains the alert outbox. A lost evaluator lease sends new traffic to Stable. A safety HOLD stops Candidate; create a new release after correcting the incident. Paused releases are not automatically restarted from old evidence.

Stop Candidate uses POST /v1/releases/<id>/rollback. A database commit failure activates the local safety fence. The response says ROLLBACK_UNCONFIRMED; candidate work and retries are rejected. Repair state access and issue Stop Candidate again. Keep v0.1 single process; the database lock enforces this requirement.

For external alerting, place the notification node between Format operational alert and Return response. Deduplicate eventId at the destination. A 2xx from the receiver means it accepted the alert, not that a human read it. The demo receiver formats and acknowledges alerts only.

## 7. Production installation requirements

- Route through your existing TLS reverse proxy and restrict admin access to operators.
- Protect/backup PostgreSQL and encryption keys; use a dedicated product database.
- Freeze the published Stable/Candidate workflows for each release; clone the next Candidate instead of editing an active one. The response version marker is a useful identity check, not cryptographic workflow attestation.
- Remove intentional fault controls from your production transforms.
- Monitor readyz, 503 rates, pending outbox records, storage growth, and observed request deadlines.
- Preserve an external copy of audit heads if independent tamper evidence is needed. A database administrator able to rewrite the whole chain and its head is outside this local chain's protection.
- Set realistic sample/window/freshness budgets for your traffic. Default minimum is 200 observations per arm plus a fresh second batch. A very low traffic workflow will hold rather than invent evidence.
- Plan request/evidence retention with the operator. v0.1 has no automatic archival or deletion policy; it retains records. This limits unattended high-volume deployment.
- Existing n8n Cloud is a possible upstream if the service is reachable over your own HTTPS origin; Cloud routing/credentials compatibility has not yet been tested in this build.

## Common failures

| Symptom | Check |
|---|---|
| HTTP 401 | Header names, spaces in Bearer value, credential selection, and client/data separation |
| Stable/Candidate 404 | Published production URL and exact path |
| Initial HOLD | Samples, minimum dwell, error confidence, and fresh batch; this is expected |
| Safety HOLD | Incomplete/stale telemetry or unhealthy Stable; inspect evidence before a new release |
| 503 safety fence | State write or rollback commit failed; use Stop Candidate after repair |
| 409 retry | Existing request still running/unknown, or changed payload |
| No alert in chat | Demo receiver only acknowledges; bind a real sink and inspect outbox retry state |
