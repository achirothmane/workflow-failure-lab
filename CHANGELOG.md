# Changelog

All notable changes to CI Retry Gate are documented here.

## [Unreleased]

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
