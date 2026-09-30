# Public incident corpus

This corpus converts resolved public CI incidents into machine-readable ground truth for
CI Retry Gate research and regression work.

Each incident records:

- the observed failure signal;
- the later-supported cause family;
- the remediation family;
- the classifier implication;
- the expected production authorization decision;
- when available, failed workflow/job identity and successful or recurrent rerun identity.

The corpus is an authorization regression contract, not a collection of anecdotes.

## V1 — terminal-symptom counterexamples

Three runner-shutdown cases establish:

`runner shutdown / exit 143 alone => no high-confidence RUNNER_INFRA authority`

All remain expected `BLOCK`.

## V2 — bidirectional controls

V2 adds three independent expected-`ALLOW` controls:

- alunduil/alunduil-chezmoi — curl connection reset;
- vtmocanu/uzi — prefixed curl connection reset;
- docker/compose — explicit external registry 502.

Each recovered on a later attempt and carries decision-time failed-step provenance.

## V3 — mechanism and evidence diversity

V3 adds:

- alethialabs-io/alethialabs — `network is unreachable`, expected `ALLOW`;
- PRQL/prql — confirmed hosted-runner loss with later recovery but missing decision-time
  step/log provenance, expected `BLOCK`;
- HiromiShikata/npm-cli-github-issue-tower-defence-management — API rate-limit failure
  recurring on the next attempt, expected `BLOCK`.

This separates three concepts that must not be collapsed:

```text
failure category != root cause != execution authority
```

A later root-cause diagnosis is useful research evidence. It does not retroactively make
missing decision-time provenance sufficient to authorize an action.

## Admission rule

A case enters only when a public source provides enough evidence to bind the visible
failure to a later diagnosis, remediation, or observable outcome.

Expected `ALLOW` cases additionally require:

- a bounded retry-safe failed job;
- high-confidence transient evidence;
- confirmed execution provenance;
- no side-effect risk;
- observable successful rerun of the same job identity.

Expected `BLOCK` cases may capture either a known unsafe cause or a known transient
cause whose authorization evidence is insufficient. Recurrent failed reruns are recorded
explicitly where available.
