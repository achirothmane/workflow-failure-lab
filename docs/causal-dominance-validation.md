# Causal Dominance Validation Evidence

Date: 2026-09-18

This document preserves the evidence used to close the current causal-dominance falsification cycle for CI Retry Gate.

## Research question

When a failed step contains a directly causal `SERVER_5XX` signal but the baseline runtime classifier says `CODE_REGRESSION` or `FLAKY_TEST`, can the transient mechanism be the upstream root cause while later deterministic-looking text is only a downstream wrapper?

The research-only implementation lives in `root_cause_precedence.py`. It does **not** modify `classify_log()`, retry authority, or production behavior.

## Evidence before Wave 4

Across the earlier causal-dominance waves, the candidate set produced:

- 11/11 ground-truth validated recoveries
- 0 observed failed-again outcomes

Those waves also exposed a causal-dominance bug: downstream failure wrappers could incorrectly outweigh an earlier causal transient mechanism. PR #39 corrected that precedence logic while preserving a hard block whenever strong primary deterministic evidence is present.

## Wave 4 holdout

GitHub Actions run:

- Run ID: `35336043067`
- Workflow/job: `Causal Dominance Wave 4 / search`
- Holdout size: 50 additional repositories
- Search window: up to 500 completed runs per repository
- Result: success

Final output:

```text
repositories_analyzed=50
repositories_skipped=0
qualifying_causal_5xx_contradictions=0
dominance_candidates=0
validated_candidate_recoveries=0
candidate_failed_again=0
authority_safe_validated_candidates=0
primary_deterministic_blocked=0
unresolved=0
candidate_independent_repositories=0
validated_candidate_independent_repositories=0
```

Wave 4 found no new causal `SERVER_5XX` contradiction, no failed-again counterexample, and no unresolved lookup.

## Current conclusion

The current research cycle is closed with:

- earlier candidate evidence: 11/11 validated recoveries
- earlier observed failed-again outcomes: 0
- Wave 4 holdout: 50/50 repositories analyzed, 0 skipped
- Wave 4 new contradictions: 0
- Wave 4 unresolved: 0

This is strong evidence for continuing to a **shadow-only override evaluation**. It is not proof of universal correctness and is not sufficient by itself to enable a production classifier override.

The next layer therefore keeps the runtime classifier unchanged and measures the causal-dominance proposal counterfactually through `causal_dominance_shadow.py`.


## Positive-Control + Holdout Gate

The 11/11 recovery result from Waves 1–3 is now preserved as an immutable evidence ledger in `causal_dominance_evidence.py`:

- Wave 1: 4 validated recoveries
- Wave 2: 1 validated recovery
- Wave 3: 6 validated recoveries
- Total: 11 validated recoveries, 0 observed failed-again outcomes in that evidence set

These 11 cases are **mechanism-family evidence**, not 11 causal-dominance positives. Most were already `UNKNOWN`, `RUNNER_INFRA`, or `DEPENDENCY_NETWORK`. The currently pinned real case that actually exercises the causal-dominance override is the SWC dprint HTTP 504 case: baseline `CODE_REGRESSION` → research-only `DOMINANCE_CANDIDATE` → `VALIDATED_RECOVERY`.

To avoid confusing specificity with sensitivity, the new validation gate combines:

1. **Real positive control** — SWC dprint must remain a dominance candidate and retain validated recovery ground truth.
2. **Deterministic negative controls** — strong assertion/type errors must block dominance even when a 5xx is present.
3. **Ordering negative control** — a failure wrapper before the 5xx must not be promoted when root-cause ordering is unproven.
4. **UNKNOWN boundary control** — ordinary UNKNOWN 5xx evidence remains outside the causal-dominance override path.
5. **50-repository holdout** — the shadow search must complete without skipped repositories, unresolved lookups, failed-again candidates, or unknown candidate outcomes.

The workflow is `.github/workflows/causal-dominance-positive-control.yml`.

### Production promotion threshold

Passing the mechanics above is intentionally **not enough** to install a production override. The current gate requires at least **3 independent real causal-dominance positive-control runs** before `production_promotion_ready` can become true.

At present the pinned count is **1/3**, so a clean positive-control + holdout run should report that the validation mechanics pass while production promotion remains blocked pending **2 additional independent real dominance-positive cases**.


## Targeted Positive-Control Search

After the combined positive-control + 50-repository holdout gate passed, production promotion remains blocked because only **1/3** independent real dominance-positive controls are pinned.

The next search is therefore targeted rather than another generic evidence wave. `causal_dominance_positive_search.py` searches only cases that already satisfy all of the following historical conditions:

- runtime category is `CODE_REGRESSION` or `FLAKY_TEST`
- mechanism causality is confirmed
- `SERVER_5XX` is the causal mechanism
- rerun outcome is ground-truth-evaluable

For each such case it re-fetches the original failed job and raw logs, re-runs `assess_causal_dominance()`, re-checks raw side-effect risk, and records:

- validated authority-safe `DOMINANCE_CANDIDATE` cases
- failed-again counterexamples
- deterministic blockers
- ordering-unproven cases
- lookup/API unresolved cases

The workflow `.github/workflows/causal-dominance-positive-search.yml` searches **100 repositories** in two 50-repository shards in parallel. The search is read-only and does not modify classifier or retry behavior.

Promotion is still fail-closed: a discovered case is only eligible to become a new pinned positive control after manual/raw-log verification and confirmation that it is independent of the existing SWC dprint case.


## pipx Direct Structural Verification

The first targeted positive search found two ground-truth-evaluable `CODE_REGRESSION` + causal `SERVER_5XX` cases in `pypa/pipx` run `31618954128`, but the search could not resolve their original failed jobs reliably after later rerun attempts. The lookup path now resolves the original failed job across all workflow attempts rather than assuming the latest/current attempt.

Those two jobs also contain `AssertionError` text, so the generic causal-dominance rule must remain conservative. A separate direct verifier now checks the pinned pipx causal chain without weakening the generic deterministic blocker:

- original failed job is from attempt 1
- the same job re-executed successfully in attempt 2
- the failure step is the test-suite step
- the log contains the exact GitHub package URL
- the same failure contains `too many 503 error responses`
- the assertion is an expectation on the install output / exit code for that exact package operation
- no side-effect authority signal is present

If those conditions hold, the direct verifier may contribute **one independent real positive-control run**. The two pipx jobs do not count as two independent runs because they share the same workflow run.

The workflow is `.github/workflows/causal-dominance-direct-verifier.yml`. A passing direct verification is research evidence only; it does not change `root_cause_precedence.py`, the production classifier, or rerun authority.
