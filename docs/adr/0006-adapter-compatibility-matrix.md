# ADR-0006: Adapter Compatibility Matrix

Status: Accepted

## Context

Wave 5 proved that the pytest, Jest, and Vitest adapters work end-to-end against one concrete version of each framework. That is necessary but insufficient for a public GitHub Action: users do not all run the same framework release, and a parser or reporter assumption can break across majors even when the core quarantine logic is unchanged.

## Decision

Maintain an executable compatibility matrix in GitHub Actions for the framework majors we claim to support.

Current validated majors:

- pytest 8 and 9
- Jest 29 and 30
- Vitest 4 and 5

The matrix uses Python 3.12 for the enforcement runtime and Node.js 22 for JavaScript framework jobs.

Each matrix cell must exercise both behavioral paths with a real runner:

1. an intentional testcase failure with an empty ACTIVE quarantine set must fail the adapter;
2. the testcase ID is extracted from that framework's actual JUnit output;
3. the same test is rerun with that exact ID in ACTIVE;
4. the adapter must succeed while reporting one quarantined failure and zero blocking failures.

## Version selection

For pytest, CI resolves the latest available release within each tested major range (for example, >=8,<9). For Jest and Vitest, CI installs the requested major from npm.

This intentionally trades exact patch reproducibility for continuous compatibility detection within declared supported majors. Wave 5 remains the pinned smoke path for a stable current-version reproduction.

## Support boundary

A framework major is only documented as supported when its matrix cell is green on the repository's current main branch.

A newly released major is not considered supported until it is added to the matrix and passes both block and quarantine paths.

If a previously supported major becomes incompatible, the preferred response is:

1. determine whether the failure is in our adapter, JUnit normalization, or an upstream breaking change;
2. repair compatibility when the change is reasonably supportable;
3. otherwise remove the major from the documented support set rather than silently masking the failure.

## Non-goals

- claiming compatibility with every plugin or custom reporter configuration;
- testing every patch release separately;
- using compatibility failures as flaky or advisory checks;
- weakening fail-closed behavior to keep older frameworks green.
