# ADR 0004: Flaky Test Intelligence Wave 1

## Status

Experimental.

## Goal

Extend the existing CI failure evidence stack from job-level retry safety to test-level flaky-test intelligence without weakening fail-closed behavior.

Wave 1 answers four questions:

1. Which individual tests have real fail-to-pass evidence on the same code revision?
2. Which tests waste the most CI time?
3. Which cases have enough evidence to investigate as flaky?
4. Which cases are safe enough to recommend temporary human-reviewed quarantine?

## Input contract

The first ingestion format is JUnit XML because it is produced by many test frameworks and avoids depending on brittle log scraping.

Each observation records:

- stable test identifier
- git SHA
- workflow run id
- attempt
- pass or fail state
- test duration
- job name

Skipped tests are excluded from pass/fail evidence.

## Evidence rule

A pass on a newer SHA is not evidence that a prior failure was flaky because code changed.

Strong Wave 1 evidence is a same-revision fail-to-pass recovery:

failure on SHA X -> later execution on SHA X -> pass

The engine counts at most one validated recovery per SHA for a test.

## Quarantine safety rule

Wave 1 never quarantines automatically.

A test becomes QUARANTINE_CANDIDATE only when:

- at least two distinct SHAs show same-revision fail-to-pass recovery, and
- at least two failures were observed, and
- no SHA has an unresolved persistent failure.

If any revision has a failure with no later same-revision pass, the recommendation is DO_NOT_QUARANTINE because automatic quarantine could hide a real regression.

A single validated recovery is INVESTIGATE, not enough evidence for quarantine.

## Waste ranking

Estimated waste is currently conservative and transparent:

failed test runtime + runtime of the pass that validates each same-revision recovery

Results are sorted by estimated waste first, then validated recoveries, then failure count.

This is intentionally simpler than a monetary estimate until runner pricing and parallelism are known.

## Non-goals for Wave 1

- automatic quarantine
- editing test source
- probabilistic ML scoring
- hidden heuristics
- cross-repository benchmarking
- deriving flakiness only from free-form logs

## Next integration

The next wave should connect this engine to GitHub Actions history by collecting JUnit artifacts across runs and attempts, then publish a test-level report or PR/check summary.
