# ReleaseGuard demo: an apparently successful release is broken

Use the local Compose stack and four imported workflows. Register demo with default production policy. Candidate and Stable enrich a lead; neither writes a record.

## Demo A: HTTP 200, wrong business result

Submit distinct lead requests with score=81 and faultCandidate="semantic". A valid enrichment requires HIGH priority when score>=70. The Candidate returns NORMAL priority while still returning a well-formed object and HTTP 200.

As soon as a request reaches Candidate, ReleaseGuard:
1. Measures the actual upstream call and rejects the cross-field business invariant.
2. Records the original Candidate observation as invalid.
3. Commits Stable-only routing and a ROLLBACK decision with CANDIDATE_OUTPUT_INVALID.
4. Queues an operational alert in the same transaction.
5. Calls read-only Stable for that request, verifies its output, and returns a valid HIGH-priority result.
6. Routes the next distinct request to Stable.

Inspect servedBy="stable", fallback=true, and the dashboard's 0% Candidate admission. A successful client response does not erase the bad Candidate observation.

## Demo B: error, partial failure, or latency

| Fault field | Value | Actual Candidate behavior |
|---|---|---|
| faultCandidate | error | Throws in the n8n Code node |
| faultCandidate | partial | Throws only when sequence is divisible by 4 |
| faultCandidate | latency | Adds 350ms inside n8n |
| faultCandidate | invalid | Returns a string instead of numeric score |
| faultCandidate | semantic | Returns priority inconsistent with score |
| faultStable | error | Stable itself throws; its failure remains visible |

The default latency budget is 3 seconds; to demonstrate a 350ms regression, use a separate demo release with maxP95Ms=250 and earlyMin=4. Production thresholds should reflect your actual business SLO. An absolute five-failure budget can stop Candidate before the full sample is available.

## Demo C: insufficient evidence

Submit a handful of successful requests and evaluate. Result: HOLD / INSUFFICIENT_SAMPLES, at the initial canary percentage. Five successful executions never constitute a validated production rollout under the default policy.

The default policy needs at least 200 observations per arm, a five-minute dwell, two fresh confirmation batches, and a 95% error-bound test. The second checkpoint requires 100 more settled observations in each arm; repeating Evaluate on unchanged data does not count.

## Demo D: successful progressive release

Create a fresh release without fault controls. Each stage gets its own evidence epoch. Observe 5%, 25%, 50%, 100%, then COMPLETED. At 100%, 10% read-only Stable probes remain enabled to provide a concurrent baseline. Subsequent invalid outputs can still trigger rollback to the retained Stable.

CI exercises all four stages through real n8n, using an explicitly accelerated test policy (20 per arm, one confirmation batch, 1ms dwell, relaxed error bounds). This validates integration/state transitions; it is not a claim that the default 5-minute policy completed instantly.

## Demo E: failed or delayed rollback commit

The PostgreSQL suite injects a real trigger rejecting the rollback status update. ReleaseGuard returns 503, emits ROLLBACK_UNCONFIRMED, and blocks further Candidate work. The persisted release remains RUNNING until repair; the product never reports Stable-only routing as confirmed in this condition.

A separate test holds a PostgreSQL row lock during rollback. The single-process safety fence takes effect before the delayed commit. Once the lock is released, the committed state becomes ROLLED_BACK.

These database fault injections belong in the disposable test suite, not a live customer database.
