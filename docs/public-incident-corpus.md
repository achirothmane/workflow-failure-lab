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

V4 adds a new admissible evidence source rather than a new anecdote.

For the PRQL hosted-runner-loss incident, GitHub's surviving check annotation can now be
consumed through an authenticated, exactly bound Checks path. That improves the incident
from unavailable provenance to confirmed runner-loss provenance.

The expected production decision remains `BLOCK`, because the failed job independently
crosses the existing release-shaped side-effect boundary.

The versioning therefore proves both properties at once:

```text
missing provenance can become confirmed
and authority can still remain denied
```

### V5

V5 adds two negative controls chosen specifically to pressure persistence and provenance boundaries:

- `actions/runner-images#13719`: `No space left on device` occurs during hosted-runner initialization before any workflow step and recurs across reruns/runner labels. This remains `BLOCK`.
- `aws-cloudformation/cfn-lint#4296` / `aws/serverless-application-model` run `19517345578`: DNS resolution fails through all three in-step retries. GitHub's latest-attempt job list later shows the same `ubuntu-latest / 3.9` identity succeeding, but the issue-preserved failure text has no runner timestamps or failed-step timing metadata. Retrospective recovery therefore does not manufacture decision-time provenance; this replay remains `BLOCK`.

V5 has 11 incidents across 11 repositories: four `ALLOW`, seven `BLOCK`.

The added controls preserve the distinction:

```text
later recovery != prior authorization evidence
runner-shaped failure != guaranteed useful immediate retry
```

## Admission rule

Expected `ALLOW` controls require a bounded retry-safe job, high-confidence transient
signal, confirmed execution provenance, no side-effect risk, and observable recovery of
the same job identity.

Execution provenance may currently be established by either:

1. timestamped causal log evidence inside the failed-step window; or
2. the authenticated runner-loss annotation fallback, exactly bound to the GitHub
   Actions check run for the failed job/head.

Expected `BLOCK` controls include unsafe causes, insufficient authority evidence,
independent side-effect boundaries, and observed immediate recurrence.
