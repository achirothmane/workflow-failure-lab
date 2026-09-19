# ADR-0005: Quarantine Enforcement Adapters

Status: Accepted

## Context

Flaky Test Intelligence can identify evidence-backed quarantine candidates and Wave 3 can maintain a temporary, human-approved ACTIVE quarantine set with expiry, regression suspension, and healthy auto-release.

The remaining problem is enforcement. A quarantine that merely exists in a manifest does not help the main CI path unless known flaky failures stop failing the workflow. However, blindly skipping quarantined tests destroys recovery evidence and can hide regressions.

## Decision

Provide framework adapters for pytest, Jest, and Vitest that:

1. run the complete test command, including quarantined tests;
2. force or configure JUnit output;
3. evaluate the resulting JUnit report against the effective ACTIVE quarantine set;
4. return success only when every attributable testcase failure belongs to ACTIVE;
5. keep CI red for every non-quarantined failure;
6. fail closed when JUnit is missing, malformed, or contains failure/error counts that cannot be attributed to a testcase;
7. upload the JUnit report using an attempt-aware artifact name so future Flaky Test Intelligence runs retain evidence;
8. never rewrite test source or silently add skip markers.

## Framework behavior

### pytest

The adapter injects `--junitxml=<path>` when the test command does not already specify JUnit output.

### Jest

The adapter injects the `jest-junit` reporter and sets `JEST_JUNIT_OUTPUT_FILE`. The consuming repository is responsible for having `jest-junit` installed.

### Vitest

The adapter enables the built-in `junit` reporter and supplies the output path.

## Safety boundary

The adapter is not allowed to reinterpret infrastructure, collection, configuration, or unattributed suite failures as quarantined test failures. If the test command exits non-zero but JUnit contains no attributable failed testcase, enforcement fails closed.

Only the Wave 3 effective ACTIVE list has masking authority. A candidate recommendation by itself has no enforcement authority.

## Feedback loop

The same quarantined tests continue to execute. Their JUnit observations therefore feed the lifecycle engine:

- continued pass-only evidence can release quarantine;
- a persistent failure revision can suspend quarantine;
- expiry removes quarantine even without an explicit repair.

## Non-goals

- automatic source-code edits;
- automatic creation of quarantine approvals;
- swallowing non-test command failures;
- shell evaluation of user-provided test commands;
- replacing framework-native test selection or retry semantics.
