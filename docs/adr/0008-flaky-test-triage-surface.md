# ADR-0008: Flaky Test Triage Surface

Status: Accepted

## Context

Flaky Test Intelligence already produced evidence, lifecycle decisions, and quarantine outputs, but developers still had to read step summaries, logs, and artifacts separately to decide what to do next.

A useful product surface should preserve the existing fail-closed authority model while reducing triage friction. It must not turn detection into automatic quarantine, and it should not require write permissions unless the user explicitly opts into a write action.

## Decision

Add a bounded triage layer on top of the existing detector and lifecycle engine.

The triage layer:

- renders a compact GitHub step-summary table with test ID, state, evidence counts, estimated waste, and a concrete next action;
- emits at most 10 GitHub workflow annotations per run so actionable tests are visible without opening raw logs;
- gives lifecycle decisions precedence over detector recommendations when both exist;
- keeps persistent-regression blocks above quarantine candidates in triage priority;
- optionally creates or updates one PR comment when `flaky-triage-comment=true`;
- uses a stable hidden marker so repeated runs update the existing triage comment instead of spamming the pull request;
- remains read-only by default.

## Authority boundary

The triage surface does not change retry or quarantine authority.

In particular:

- `QUARANTINE_CANDIDATE` remains advisory and requires human approval;
- `ACTIVE` still comes only from the version-controlled quarantine manifest;
- `BLOCKED_REGRESSION` remains fail-closed;
- annotations and comments cannot activate or renew a quarantine;
- quarantined tests continue to execute so recovery and regression evidence remains observable.

## PR comment permissions

PR comments are opt-in because they require write permission.

When enabled, the workflow token must be able to create or edit pull-request issue comments. The action treats comment publication as a presentation concern: API failure produces a warning and leaves the underlying test/quarantine decision unchanged.

When no pull request can be associated with the analyzed run, the action emits a warning and does not post anywhere else.

## Bounded output

To avoid noisy CI:

- the summary/PR table shows at most 20 triage rows;
- workflow annotations are capped at 10 per run;
- one marker-owned PR comment is updated in place rather than appended repeatedly.

## Outputs

The action exposes:

- `flaky-triage-items`
- `flaky-triage-annotations`
- `flaky-triage-comment-posted`

These outputs are observational only and do not grant retry or quarantine authority.
