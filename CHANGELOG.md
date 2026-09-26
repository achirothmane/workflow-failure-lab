# Changelog

All notable changes to CI Retry Gate are documented here.

## [Unreleased]

## [1.1.0] - 2026-09-26

### Added

- Policy-free CI Evidence Producer with explicit OBSERVED, DERIVED, INFERRED, and evidence-quality layers.
- Canonical `evidence-producer.ci.v1` EvidenceBundle contract for retry authorization.
- Canonical `*.evidence.json` runtime artifacts with deterministic serialization and SHA-256 integrity verification.
- Separate-process Evidence Gate CLI so authorization consumes persisted evidence rather than in-memory assessment objects.
- New Action outputs: `evidence-bundle-path` and `evidence-bundle-sha256` for audit, replay, and downstream verification.

### Changed

- CI Retry Gate now consumes EvidenceBundle as its evidence boundary instead of reading `JobAssessment` directly.
- Retry policy remains outside the evidence artifact, preserving the distinction between observed evidence and execution authority.
- Missing, malformed, conflicting, or tampered evidence fails closed to BLOCK.
- Recovery and recurrence checks remain conservative outer guards: they can narrow an ALLOW to BLOCK but cannot create authorization.

### Verification

- 353 Python tests pass, including artifact tamper detection and process-boundary authorization tests.
- CI, pytest/Jest/Vitest Compatibility Matrix, Remote v1 Consumer E2E, clean-install verification, and Release Readiness all pass on the release candidate.


## [1.0.2] - 2026-09-24

### Added

- Setup Doctor composite action at `/doctor@v1` with READY/WARN/BLOCKED onboarding diagnostics.
- Framework detection for pytest, Jest, and Vitest, including fail-closed Jest `jest-junit` validation.
- Read-only checks for JUnit artifact wiring, GitHub API read access, ownership routing, quarantine manifests, and recommended feature permissions.
- Monorepo-safe `working-directory`, GitHub step-summary guidance, and a generated production configuration.

### Changed

- PR comments are now explicit opt-in: `comment-on-pr` defaults to `false` in both the Action contract and runtime fallback.
- README installation examples and badges now use the current `achirothmane` repository owner.
- Release-readiness checks now enforce the read-only comment default and current repository identity.

## [1.0.1] - 2026-09-19

### Changed

- Shortened the GitHub Action Marketplace description to satisfy the 125-character metadata limit.
- Refreshed stable release guidance for the `@v1` consumer reference.

## [1.0.0] - 2026-09-19

### Added

- Conservative failure classification for runner/infrastructure, dependency/network, timeout, flaky-test, code-regression, and unknown failures.
- Execution Provenance and Failure-Step Outcome Provenance gates.
- Selective rerun mode with side-effect and attempt-cap boundaries.
- Failure fingerprints, CI history analysis, CI-waste reporting, and conservative policy learning.
- Policy Shadow Mode and cross-repository Benchmark Mode.
- Recovery Ground Truth so later success is not treated as proof of transience unless the failed step genuinely re-executed successfully.
- Coverage Attribution, Rejection Intelligence, UNKNOWN Failure Intelligence, semantic promotion, transient-mechanism causality, and independent-replication research gates.
- Targeted SERVER_5XX counterexample research and causal-dominance shadow validation.
- Causal-dominance evidence corpus with two independent real positive-control runs currently pinned (SWC and pipx).

### Safety

- Automatic rerun remains disabled by default.
- `auto-rerun` and `selective-rerun` cannot be enabled together.
- Deploy/publish/migration/release and other side-effect signals remain blocked.
- Causal Dominance remains research/shadow-only and is **not** wired into production retry authority.
- Production promotion for Causal Dominance remains blocked at 2/3 independent real positive controls.

### Changed

- Product name and public positioning now use **CI Retry Gate**.
- Release version is prepared as `1.0.0`.
- Repository licensing is now explicitly MIT.

## [0.1.0] - 2026-07-19

Initial public release under the Workflow Failure Lab name.
