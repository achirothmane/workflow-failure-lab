# Authenticated runner annotation evidence

## Problem

A GitHub Actions runner can disappear before its job log is finalized. In that state the
job may have no usable log blob or failed-step metadata, while GitHub still exposes a
failure annotation on the corresponding check run.

Treating missing logs as `EVIDENCE_UNAVAILABLE` is safe but leaves a real coverage gap.

## Source

CI Retry Gate queries the GitHub Checks endpoints only after ordinary job-log acquisition
fails:

```text
GET /repos/{owner}/{repo}/check-runs/{check_run_id}
GET /repos/{owner}/{repo}/check-runs/{check_run_id}/annotations
```

The token must be present and have `checks: read` for private-repository use.

## Trust and binding contract

The annotation is not trusted merely because its text looks familiar.

CI Retry Gate requires:

```text
job.check_run_url.id == fetched_check_run.id
job.name             == fetched_check_run.name
job.head_sha         == fetched_check_run.head_sha
job.conclusion       == fetched_check_run.conclusion == failure/timed_out
check_run.status     == completed
check_run.app.slug   == github-actions
annotation.level     == failure
annotation.message   == exact runner-loss prefix
```

Only then is execution provenance marked `CONFIRMED` for the check-run-bound evidence
source.

This is different from failed-step provenance. A dead runner may not leave a completed
failed step at all. The evidence source is therefore the exact failed check execution,
not a fabricated step window.

## Fail-closed cases

The fallback does not authorize when:

- the token is absent;
- Checks access returns an error;
- `check_run_url` is absent or malformed;
- id, name, SHA, conclusion, status, or app identity do not match;
- the annotation is warning/notice rather than failure;
- the text only mentions runner loss in surrounding prose;
- the job carries side-effect risk;
- the retry limit has been reached.

If any of these occur, the original missing-log failure remains
`EVIDENCE_UNAVAILABLE`.

## Scope

V1 recognizes only the GitHub runner-loss annotation family. It does not turn arbitrary
check annotations into classifier input.

The path is intentionally narrow because check annotations can contain ordinary workflow
errors as well as GitHub control-plane errors. New annotation families require their own
public ground truth and replay controls before becoming authorizing evidence.
