# ADR-0007: Stable v1 Remote Consumer Gate

Status: Accepted

## Context

Local composite-action tests can prove Python logic and repository-relative adapter wiring, but they do not prove that consumers can resolve the stable release line through GitHub's remote action packaging path.

A public GitHub Action needs evidence that the stable `v1` reference itself contains the expected root action and framework adapters, and that those remote references preserve the same fail-closed behavior as local tests.

## Decision

Maintain an end-to-end workflow that invokes the stable release line exclusively through remote references:

- `othy19904-eng/workflow-failure-lab@v1`
- `othy19904-eng/workflow-failure-lab/adapters/pytest@v1`
- `othy19904-eng/workflow-failure-lab/adapters/jest@v1`
- `othy19904-eng/workflow-failure-lab/adapters/vitest@v1`

The root action must load and return outputs with rerun modes disabled under read-only Actions/content permissions.

Each framework adapter must:

1. execute a consumer-owned intentional failure with an empty ACTIVE set and remain red;
2. emit JUnit;
3. have the consumer independently derive the failing testcase ID without importing product parsing code;
4. rerun the same failure through the remote adapter with that ID ACTIVE;
5. return green with exactly one quarantined failure and zero blocking failures;
6. upload discover and quarantine JUnit reports as attempt-aware workflow artifacts.

## Stable branch policy

The movable `v1` branch represents the stable major release line.

Before a Wave 7 test, `v1` may be fast-forwarded to a commit that has already passed normal CI and compatibility validation. Force updates are not part of this process.

A stable-line move is considered validated only after the remote-consumer workflow succeeds against that remote `@v1` reference.

## Current limitation

The connected GitHub tool available to this project cannot create a second repository. Therefore this gate runs from a consumer-isolated fixture and workflow inside the same repository while resolving the product exclusively through remote `@v1` references.

This proves GitHub remote action resolution, packaging, permissions, adapter execution, outputs, and artifact upload. It does not claim to be a separate-repository installation test.

A true cross-repository consumer fixture remains the preferred extension when repository-creation or a dedicated consumer repository is available.

## Safety properties

- no force movement of the stable `v1` branch;
- no rerun authority enabled during packaging validation;
- consumer testcase identification is independent from product code;
- artifact production is verified from GitHub after the workflow run;
- local smoke and compatibility matrix remain separate gates rather than being replaced by this workflow.
