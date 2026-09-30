# D00 Native CI Baseline Recipe

Status: preregistered comparator recipe. No execution performed by D00.

## Task

For one exact owner-controlled failed GitHub Actions execution, evaluate the same bounded eligibility and identity constraints intended for D01, then use GitHub-native rerun handling only for that exact run/attempt.

Required bindings:

- repository;
- workflow;
- run ID;
- head SHA;
- run attempt;
- account/owner context;
- permitted rerun operation.

## Native arm procedure

1. Record the exact identifiers before mutation.
2. Confirm the task is eligible under the same safety/outcome standard that D01 will use.
3. Confirm the operator is using existing owner-controlled GitHub authority.
4. Trigger only the bounded GitHub-native rerun operation through the GitHub UI/CLI/API already controlled by the owner.
5. Record whether the provider accepted the request.
6. Observe the new attempt separately from request acceptance.
7. Observe later workflow result separately from attempt creation.
8. Record operator active labor, waiting/provider latency and touches under D00.
9. Preserve BLOCK/UNKNOWN/failure in the denominator.

## Trust boundary

The native arm does not grant write authority to WFL analysis code or a remote evaluator. The privileged write remains in the owner-controlled GitHub path.

## Fairness rule

The native arm must not be intentionally unsafe or simplified to make the governed arm look better. It receives the same task semantics, permitted operation, identity binding and outcome standard.

## Review attribution

Repository-owner/maintainer review is recorded by the PR/merge history that adopts this preregistration. No independent reviewer is claimed by D00.
