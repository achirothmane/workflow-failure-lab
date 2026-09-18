# ADR 0003: SERVER_5XX counterexample evidence

- Status: Accepted
- Date: 2026-09-18
- Scope: shadow research only; no runtime classifier or rerun-authority change

## Context

The shadow hypothesis under investigation is:

`causal SERVER_5XX evidence bound to the failed step -> transient dependency/network failure candidate`

Before considering any runtime promotion, the project added a broad counterexample search that scans causal `SERVER_5XX` evidence across **all runtime categories**, not only `UNKNOWN`.

The purpose is falsification: look for either

1. a ground-truth-evaluable causal `SERVER_5XX` failure whose genuine rerun fails again; or
2. a causal `SERVER_5XX` match classified into a non-transient deterministic category.

The search is read-only. It does not modify `classify_log()` and does not grant rerun authority.

## Evidence run

GitHub Actions run:

- Workflow: `SERVER 5XX Counterexample 50 Repo`
- Run ID: `35328309125`
- Run URL: https://github.com/othy19904-eng/workflow-failure-lab/actions/runs/35328309125
- Completed: 2026-09-18
- Conclusion: `success`
- Repositories requested/analyzed: 50 / 50
- Repositories skipped: 0
- History window: up to 500 workflow runs per repository

The benchmark branch commit `f0e0586da7e13e1e213f34fe0f3afbc2c15f932c` was exactly one commit ahead of production `main` commit `838874217bbb7a18d8e4b997f60c52805677d164`, and that one commit only added the benchmark workflow file. The production analysis code exercised by the benchmark therefore matched `main`.

## Result

```text
repositories_analyzed=50
repositories_skipped=0
causal_matches=4
evaluable_matches=4
validated_recoveries=4
failed_again=0
unknown_outcomes=0
observed_recovery_rate=1.000000
classification_contradictions=0
side_effect_matches=2
independent_runs=3
independent_repositories=3
category_counts=(('DEPENDENCY_NETWORK', 2), ('UNKNOWN', 2))
```

Ground-truth-evaluable matches came from:

- `docker/compose`: two causal HTTP 502 failures in the same workflow run, both validated recoveries; both were side-effect-boundary matches.
- `serde-rs/serde`: causal HTTP 500 failure, `UNKNOWN`, validated recovery, no side-effect signal.
- `traefik/traefik`: causal HTTP 504 failure, `UNKNOWN`, validated recovery, no side-effect signal.

## Decision

The broad counterexample-search phase is complete for this evidence round.

No outcome counterexample was found: every ground-truth-evaluable causal `SERVER_5XX` match recovered on a genuine rerun.

No classification contradiction was found: causal `SERVER_5XX` did not coexist with a non-transient deterministic category in this sample.

However, **four evaluable matches are not enough to treat the hypothesis as proven or to promote the shadow rule into runtime classification**. Two of the four matches are also authority-blocked by the side-effect boundary.

Therefore:

- keep `SERVER_5XX_CAUSAL_UNKNOWN` shadow-only;
- keep all existing execution-provenance, side-effect, retry-cap, and policy gates unchanged;
- do not weaken any safety boundary to increase coverage;
- do not add another classifier feature merely because this benchmark was clean;
- resume promotion research only when materially more independent ground-truth evidence is available, especially non-side-effect matches.

## Interpretation

This benchmark strengthens the transient-mechanism hypothesis and failed to falsify it in a broad 50-repository search. It is evidence, not a guarantee of future behavior.

The next useful gain is **more independent evidence**, not another layer of code around the same four samples.
