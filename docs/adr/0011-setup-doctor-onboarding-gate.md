# ADR-0011: Setup Doctor and Onboarding Gate

Status: Accepted

## Context

CI Retry Gate now spans retry safety, flaky-test intelligence, quarantine lifecycle, framework adapters, triage, ownership routing, and managed Issue lifecycle.

That breadth creates a new product risk: a correct engine can still feel broken when a consumer repository is missing JUnit artifact wiring, `jest-junit`, a valid ownership/quarantine file, or the required GitHub token permissions.

The product therefore needs a preflight surface that explains setup problems before users enable write behavior.

## Decision

Add a separate read-only composite action at:

`othy19904-eng/workflow-failure-lab/doctor@v1`

The doctor inspects the checked-out consumer repository and returns one of three check levels:

- `PASS`
- `WARN`
- `BLOCKED`

The overall verdict is `READY` when no BLOCKED check remains.

## Checks

Wave 11 validates:

- supported framework detection for pytest, Jest, and Vitest;
- explicit framework selections against detected project evidence;
- the required `jest-junit` dependency when Jest is selected;
- visible JUnit artifact-prefix wiring in GitHub workflow files;
- CODEOWNERS and the explicit flaky ownership map when ownership routing is requested;
- quarantine manifest presence and schema/TTL validation when quarantine lifecycle is requested;
- read-only repository and Actions API access;
- required workflow permission recommendations for rerun, PR-comment, and Issue-lifecycle features.

Monorepo inspection is scoped by a repository-relative `working-directory` that must remain inside `GITHUB_WORKSPACE`.

## Write-permission boundary

The doctor must remain read-only.

It may recommend `actions: write`, `pull-requests: write`, or `issues: write`, but it must never verify those permissions by:

- triggering a rerun;
- posting a PR comment;
- creating or mutating an Issue;
- changing a quarantine manifest.

This preserves a clean separation between diagnosis and authority.

## Fail behavior

`fail-on-blocked` defaults to `true`.

BLOCKED findings therefore fail the doctor job by default. WARN findings are visible in annotations and the GitHub step summary but do not fail the job.

Consumers may set `fail-on-blocked=false` only when they explicitly want an advisory report.

## Output surface

The doctor exposes:

- `ready`
- `blocked-checks`
- `warnings`
- `detected-frameworks`
- `required-permissions`

The GitHub step summary also prints a recommended production YAML configuration derived from the requested features.

## Non-goals

Wave 11 does not auto-edit workflow files, install dependencies, grant permissions, create manifests, or silently change repository configuration.

Its job is to reduce adoption friction by making missing prerequisites concrete before production rollout.
