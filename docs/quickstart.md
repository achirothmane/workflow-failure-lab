# CI Retry Gate — 5-minute quickstart

This guide is the shortest path from **"I found the project"** to **"I have a useful decision on a real CI failure."**

CI Retry Gate is conservative by design. Start read-only, observe decisions, then enable write behavior only if the evidence is useful for your repository.

## Option A — try it without installing anything

Use the public-run analyzer:

**https://github.com/achirothmane/workflow-failure-lab/issues/new?template=public-run-analysis.yml**

Provide:

- a public repository in `owner/repo` form;
- a failed GitHub Actions run ID.

The analyzer does not modify the target repository.

A result looks like:

```text
Decision: BLOCK
Evidence: CONTRADICTED
Next action: STOP_RETRY_LOOP
Eligible failed jobs: 0
Blocked failed jobs: 1
```

The useful question is not "did the tool say ALLOW?" It is:

> Did the result make the retry-versus-investigate decision clearer?

If not, stop here.

## Option B — install report-only mode

Create:

`.github/workflows/ci-retry-gate.yml`

with:

```yaml
name: CI Retry Gate

on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]

permissions:
  actions: read
  checks: read

jobs:
  retry-gate:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - uses: achirothmane/workflow-failure-lab@v1
        with:
          github-token: ${{ github.token }}
          auto-rerun: 'false'
          selective-rerun: 'false'
```

This evaluates failed runs but does not rerun them.

## Run Setup Doctor before enabling writes

Create a temporary manual workflow:

```yaml
name: CI Retry Gate Doctor

on:
  workflow_dispatch:

permissions:
  contents: read
  actions: read
  checks: read

jobs:
  doctor:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - id: doctor
        uses: achirothmane/workflow-failure-lab/doctor@v1
        with:
          github-token: ${{ github.token }}
          source-workflow: 'CI'
          rerun-mode: 'none'
```

Doctor reports one of:

- `READY`
- `WARN`
- `BLOCKED`

and gives concrete fixes.

## Recommended rollout

1. Analyze one historical failure.
2. Install report-only mode.
3. Run Setup Doctor.
4. Observe decisions on real failures.
5. Enable only the write behavior you actually need.

## Stable interface

Use:

`achirothmane/workflow-failure-lab@v1`

for the stable v1 line.

For immutable builds, pin an exact release tag or commit SHA.

## Next

- [README](../README.md) — product overview
- [Product architecture](product-architecture.md) — how the system is organized
- [Technical reference](technical-reference.md) — full inputs, outputs, and implementation details
- [Examples](../examples/README.md) — copy-ready workflows and fixtures
