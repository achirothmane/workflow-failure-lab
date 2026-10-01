# GitHub Marketplace Packaging

## Product name

**CI Retry Gate**

## One-line promise

Evidence-backed `ALLOW` / `BLOCK` decisions before rerunning failed GitHub Actions jobs.

## Short description

CI Retry Gate evaluates failed GitHub Actions runs before retry, using provenance, recurrence, side-effect boundaries, and exact workflow-state binding. Insufficient or contradictory evidence fails closed.

## Long description

A failed GitHub Actions job does not tell you whether retrying it is justified.

CI Retry Gate sits between failure and rerun. It inspects the failed workflow, builds an evidence record, applies a conservative retry policy, and returns a deterministic `ALLOW`, `BLOCK`, or evidence-unavailable result before any rerun is authorized.

The default path is read-only. Teams can start with a zero-install analysis of a public failure, then use Setup Doctor to validate permissions and generate a copy-ready activation workflow.

When write behavior is enabled explicitly, retry authority remains bounded to the exact workflow state that produced the evidence. If the run attempt, head SHA, workflow identity, failed-job set, authority, or relevant evidence changes, the old justification cannot be reused.

### Highlights

- evidence-backed retry decisions rather than blind reruns;
- exact binding to workflow state and failed-job identity;
- conservative fail-closed behavior for missing or contradictory evidence;
- side-effect-aware authorization;
- selective rerun mode with bounded retry attempts;
- Decision Experience with deterministic operator next actions;
- report-only fleet analysis;
- Setup Doctor with copy-ready activation workflow generation;
- public zero-install evaluation path;
- historical recovery and recurrence evidence;
- flaky-test intelligence, ownership routing, and managed triage surfaces.

### Start without installing

Use the repository's **Analyze a public GitHub Actions failure** flow to inspect one public workflow run with zero target-repository writes.

### Install

Stable major release:

```yaml
- uses: achirothmane/workflow-failure-lab@v1
```

Exact release:

```yaml
- uses: achirothmane/workflow-failure-lab@v1.4.1
```

### Default safety posture

- automatic rerun: off;
- selective rerun: off;
- public analysis: read-only;
- insufficient evidence: block;
- contradictory evidence: block;
- side-effect boundary: independent blocker;
- historical flakiness: non-authorizing;
- descriptive and fleet reports: non-authorizing.

### Permissions

Read-only evaluation uses the minimum documented GitHub Actions permissions. Write permissions are required only for explicitly enabled mutation features such as reruns or comments.

Run Setup Doctor before enabling write behavior.

### Evidence and verification

The stable `@v1` line is continuously exercised from a separate consumer repository. Release candidates also pass repository CI, compatibility tests, Public Incident Replay, clean-install verification, and release-readiness checks.

### License

MIT.

## Suggested discovery terms

- GitHub Actions
- CI
- CI/CD
- retry
- flaky tests
- test reliability
- DevOps
- workflow reliability
- incident evidence
- automation safety

## Suggested Marketplace categories

Choose the closest available GitHub Marketplace categories for:

1. Continuous integration / CI
2. Utilities / workflow management

Confirm the exact category labels in the Marketplace publishing UI before publication.

## Screenshot order

1. CI Retry Gate product flow — `docs/ci-retry-gate-hero.png`
2. Setup Doctor overview — `docs/setup-doctor-overview.png`

## Primary CTA

**Analyze one real public failure before installing.**

Secondary CTA:

**Run Setup Doctor before enabling write behavior.**
