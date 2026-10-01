# Historical Flakiness — Independent Public-Repository Backtest

Date: 2026-09-28

## Question

Can strictly-prior test history add useful evidence to a production
`BLOCK / UNKNOWN` retry decision on repositories not controlled by this
project, while leaving production authorization unchanged?

This document records a public-repository backtest. It is not a promotion
decision and does not change the production evidence gate.

## Discovery scan

A read-only scan evaluated public GitHub Actions reruns across repositories that
publish or reference JUnit/test-result artifacts.

Observed scan totals:

```text
repositories scanned: 15
repositories with reruns: 12
failed test-like jobs classified: 71
jobs classified UNKNOWN: 54
UNKNOWN jobs in runs containing any JUnit-like artifact: 10
```

The last count is deliberately broad. A JUnit artifact elsewhere in the same run
does not prove that it belongs to the UNKNOWN job or to the failed attempt.

Manual provenance checks removed false candidates including:

- post-test aggregation jobs whose JUnit artifacts belonged to upstream pytest shards;
- failures before test execution, where attempt-1 JUnit did not exist;
- browser-test failures where available JUnit artifacts belonged to unrelated Rust jobs;
- setup/dependency failures that occurred inside a job named "test" but before a test
  observation could be produced.

This filtering is required before historical test evidence can be considered
applicable.

## First independent UNKNOWN + JUnit + recovery case

Repository:

```text
opral/lix
```

GitHub Actions run:

```text
36048130839
```

Failed job:

```text
Cargo E2E Test
```

Production classifier result in the independent scan:

```text
category   = UNKNOWN
confidence = low
```

Attempt provenance:

```text
attempt 1
  conclusion: failure
  run_started_at: 2026-09-24T19:26:13Z
  updated_at:     2026-09-24T19:43:45Z

attempt 2
  conclusion: success
  run_started_at: 2026-09-24T19:44:03Z
  updated_at:     2026-09-24T19:54:14Z

head_sha:
  f54bd1cbc58bb915fa96553390ce59df19bc97e0
```

The SHA is identical across both attempts.

The run preserved two artifacts with the same name:

```text
rust-nextest-junit-e2e
```

Artifact timestamps placed one artifact uniquely inside attempt 1 and the other
uniquely inside attempt 2. The temporal-binding logic introduced for duplicate
unsuffixed artifacts therefore resolved both attempts without guessing.

## Ground truth

The attempt-1 runner log showed a real nextest execution:

```text
256 tests run
255 passed
1 failed
test aborted with signal 6: SIGABRT
```

The corresponding JUnit identity was:

```text
lix_e2e::sync_mode::small_file_observer_receives_remote_edit_without_a_chunk_round_trip
```

A targeted backtest using the repository's production history collector scanned:

```text
workflow runs scanned:         50
JUnit artifacts seen:          23
JUnit artifacts analyzed:      23
ambiguous artifacts skipped:    0
test observations:           5932
```

The exact attempt-1 failed test was observed again as PASS in attempt 2 on the
same SHA.

Therefore this case establishes independent ground truth for:

```text
Production classifier: UNKNOWN
        +
attempt-1 JUnit failure
        +
same-SHA attempt-2 JUnit pass
        =
observed recovery
```

## Strictly-prior historical result

The shadow evaluation was executed retrospectively as if the decision point were
attempt 1. Current-run attempt 2 was therefore future evidence and was not
eligible to support the decision.

Result:

```text
baseline.decision        = BLOCK
baseline.evidence_status = UNKNOWN

shadow.status             = NO_PRIOR_EVIDENCE
current_failed_tests      = 1
prior_observations        = 0
validated_recoveries      = 0
historical_support        = 0
historical_contradiction  = 0

authorization.changed     = false
```

The recovered test had no eligible strictly-prior observations in the scanned
history.

## Interpretation

This is the first independent case in this validation wave that satisfies all of
the following:

1. the production classifier was UNKNOWN;
2. the failure occurred during real test execution;
3. attempt-1 JUnit existed;
4. attempt-2 JUnit existed on the same SHA;
5. the failed test recovered on rerun.

However, it does **not** validate the current historical-support rule.

The correct retrospective result was:

```text
real recovery
+
no prior evidence
=
NO_PRIOR_EVIDENCE
```

This is a useful negative result. The shadow did not manufacture support after
seeing a later recovery, and future evidence did not leak backward into attempt 1.

## Other observed counterexamples

The public scan also found several cases where historical test evidence should not
be applied:

- `opennextjs/opennextjs-netlify`: UNKNOWN cache-restore failure occurred before
  attempt-1 tests produced JUnit;
- `opral/lix` browser test: UNKNOWN test timeout recovered, but the available
  JUnit artifacts belonged to separate Rust jobs;
- `shishobooks/shisho`: Go test jobs recovered after dependency-download
  `INTERNAL_ERROR` failures, but the failed shard produced no JUnit artifact;
- `OCHA-DAP/hdx-ckan`: a job named `test` failed during environment setup before
  pytest execution and produced no artifacts.

These cases reinforce that job names and run-level artifact presence are
insufficient provenance.

## Current decision

Do not promote historical flakiness into production retry authority.

Keep:

```text
Historical Flakiness Evidence Producer
        ↓
Historical Flakiness Shadow
        ↓
read-only evidence
```

Do not change:

```text
evidence_gate.py
production ALLOW/BLOCK authority
```

The promotion gate still requires multiple independent cases where:

- production baseline is `BLOCK / UNKNOWN`;
- a current test failure has valid JUnit provenance;
- strictly-prior history exists for the same test identity;
- historical support is emitted before the rerun outcome is known;
- later ground truth confirms recovery or failure;
- false-positive would-ALLOW remains zero.

## Next validation target

The next useful sample is no longer merely "an UNKNOWN that recovers."

It is specifically:

```text
UNKNOWN current test failure
        +
strictly-prior same-test recovery history
        ↓
shadow support before outcome
        ↓
independent rerun ground truth
```

Until such samples exist in sufficient number, historical support remains an
experimental evidence channel rather than execution authority.
