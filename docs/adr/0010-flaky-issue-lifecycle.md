# ADR-0010: Deduplicated Flaky Issue Lifecycle

Status: Accepted

## Decision

Add an opt-in GitHub Issue lifecycle for test-level triage. It is disabled by default and requires `issues: write`.

A managed Issue is identified by a deterministic SHA-256 fingerprint of the exact test ID. The fingerprint is present in both the Issue title and a hidden body marker. Repeated runs search for that marker and update the same Issue instead of creating another one.

Actionable states that may create an Issue are:

- `QUARANTINE_CANDIDATE`
- `INVESTIGATE`
- `ACTIVE`
- `EXPIRED`
- `BLOCKED_UNVERIFIED`
- `BLOCKED_REGRESSION`

`DO_NOT_QUARANTINE` does not create a new Issue by itself, avoiding an Issue for every ordinary failing test. If a managed Issue already exists, current evidence may still update/reopen it.

Only `RELEASED_HEALTHY` automatically closes a managed Issue.

## Safety boundaries

Issue lifecycle is presentation/workflow state only. It cannot authorize retries, quarantines, or assignments. Owners remain rendered as code spans and are not automatically mentioned or assigned.

Writes are capped per run. The default is 10 changes and the allowed range is 1–50. Items beyond the cap are deferred rather than silently written later.

Issue API failures produce warnings and do not change retry/quarantine decisions.

## Deduplication

Each test receives a deterministic hidden marker:

`<!-- ci-retry-gate-flaky-issue:<sha256(test_id)> -->`

The visible title also includes the first 16 fingerprint characters. Existing Issues are discovered through GitHub Issue search and verified by the full hidden marker before update/reopen/close.

## Outputs

- `flaky-issues-created`
- `flaky-issues-updated`
- `flaky-issues-reopened`
- `flaky-issues-closed`
- `flaky-issues-deferred`
