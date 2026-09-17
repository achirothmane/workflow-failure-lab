# Policy Shadow Mode

Policy Shadow Mode validates learned retry policies without allowing them to execute.

Enable it with:

```yaml
- uses: othy19904-eng/workflow-failure-lab@v1
  with:
    github-token: ${{ github.token }}
    policy-shadow-mode: 'true'
    history-runs: '20'
    auto-rerun: 'false'
    selective-rerun: 'false'
```

The mode is read-only and needs only `actions: read` plus `contents: read` for the surrounding workflow.

## What it measures

The backtest walks historical first-attempt failures in chronological order. At each point it builds the policy from older evidence only. If that prior evidence would have produced `AUTO_RERUN_ONCE`, the point becomes a shadow decision.

When a real historical rerun exists, its result is used as the observed outcome:

- `RECOVERED`: the real later execution succeeded;
- `NOT_RECOVERED`: a real later execution occurred but did not succeed;
- `UNKNOWN`: no real rerun occurred, so the counterfactual cannot be known.

This avoids using a future outcome to decide whether the policy would have fired at that earlier point.

## Outputs

- `shadow-decisions`
- `shadow-evaluated-decisions`
- `shadow-recoveries`
- `shadow-false-positives`
- `shadow-unknown-outcomes`
- `shadow-observed-precision`
- `shadow-recoverable-failed-minutes`

Observed precision is `recoveries / evaluated decisions`. Unknown outcomes are excluded rather than guessed.

`shadow-recoverable-failed-minutes` is deliberately not called CI savings. It is the failed-job runtime represented by observed recoveries. A rerun also consumes runner time, so actual billed-minute or engineering-time savings require a broader cost model.

## Safety

Shadow Mode never calls a rerun endpoint and never promotes a learned policy to enforcement. It exists to gather evidence before an operator chooses whether a policy is trustworthy enough to enforce later.

It is opt-in because the current implementation performs a second history scan to keep Shadow Mode isolated from the existing History/Policy Learning path. A future optimization can share the same collected history without changing the shadow semantics.
