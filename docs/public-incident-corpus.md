# Public incident corpus

This corpus converts resolved public CI incidents into machine-readable ground truth for
CI Retry Gate research and regression work.

The corpus records:

- the observed failure signal;
- the later-supported cause family;
- the remediation family that resolved or contained the failure;
- the classifier implication for CI Retry Gate.

It deliberately does **not** copy repository-specific fixes into the product. A Python
cache-size reduction, a Rust mutation-test memory scope, and a Go fuzz-process address
space limit are different fixes. What transfers into CI Retry Gate is the causal lesson
they jointly support.

The initial V1 set is intentionally small and high-confidence. New entries should be
added only when a public issue/PR provides enough evidence to connect the observed CI
symptom to a later diagnosis, remediation, or validated outcome.

Current invariant:

`terminal CI symptom != root-cause proof`

In particular:

`runner shutdown / exit 143 alone => no high-confidence RUNNER_INFRA`
