# Public incident corpus

This corpus converts resolved public CI incidents into machine-readable authorization
ground truth for CI Retry Gate.

Each incident records the observed signal, later-supported cause family, remediation
family, classifier implication, expected production decision, and available failed/rerun
identity.

The corpus is a regression contract, not a collection of anecdotes.

## Versioned evidence growth

### V1

Three runner-shutdown counterexamples establish that terminal
`shutdown + exit 143` is not independent proof of runner infrastructure. All are
`BLOCK`.

### V2

Three independent positive controls add connection-reset and explicit external HTTP 502
recoveries. The corpus becomes bidirectional.

### V3

Three mechanism-diverse controls add:

- dependency `network is unreachable` -> `ALLOW`;
- hosted-runner loss with missing decision-time provenance -> `BLOCK`;
- recurring GitHub API rate-limit failure -> `BLOCK`.

This establishes:

```text
failure category != root cause != execution authority
```

### V4

V4 does not add an anecdote. It adds a new admissible evidence source.

The PRQL hosted-runner-loss incident remains the same ground-truth event, but GitHub's
surviving check annotation is now consumed through an authenticated, exactly bound
Checks path. That changes only this case from V3 `BLOCK` to V4 `ALLOW`.

The versioning is deliberate: V3 proves the system failed closed before the evidence
source existed; V4 proves the new source closes that gap without changing the other
eight decisions.

## Admission rule

Expected `ALLOW` controls require a bounded retry-safe job, high-confidence transient
signal, confirmed execution provenance, no side-effect risk, and observable recovery of
the same job identity.

Execution provenance may currently be established by either:

1. timestamped causal log evidence inside the failed-step window; or
2. the authenticated runner-loss annotation fallback, exactly bound to the GitHub
   Actions check run for the failed job/head.

Expected `BLOCK` controls include unsafe causes, insufficient authority evidence, and
observed immediate recurrence.
