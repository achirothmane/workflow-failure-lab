# Public incident corpus

This corpus converts resolved public CI incidents into machine-readable ground truth for
CI Retry Gate research and regression work.

Each incident records:

- the observed failure signal;
- the later-supported cause family;
- the remediation family that resolved or contained the failure;
- the classifier implication;
- the expected production authorization decision;
- when available, the failed workflow run/job and successful rerun job identity.

It deliberately does **not** copy repository-specific fixes into the product. What
transfers into CI Retry Gate is the causal and authorization lesson.

## V1 — denial-side counterexamples

The initial three cases are runner-shutdown counterexamples. They establish:

`runner shutdown / exit 143 alone => no high-confidence RUNNER_INFRA`

and therefore remain expected `BLOCK` controls.

## V2 — bidirectional corpus

V2 adds three independent expected-`ALLOW` controls:

- alunduil/alunduil-chezmoi — curl connection reset, same job recovered on attempt 2;
- vtmocanu/uzi — curl connection reset, same job recovered on attempt 2;
- docker/compose — repeated registry 502, same build job recovered on attempt 2.

These controls are intentionally cases the current production gate should understand
without a research-only classifier override.

## Admission rule

A new case enters the corpus only when a public source provides enough evidence to bind
the visible failure symptom to a later diagnosis, remediation, or ground-truth outcome.
Expected `ALLOW` cases additionally require a bounded retry-safe failed job, confirmed
execution provenance, and an observable successful rerun of the same job identity.

The corpus is a regression contract, not a collection of anecdotes.
