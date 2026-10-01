# v1 Release Readiness

This checklist covers the CI Retry Gate v1 release line. The current release target is `v1.4.1`.

## Required before tagging

- [ ] Repository CI passes on the exact release-candidate commit.
- [ ] Compatibility Matrix passes on the exact release-candidate commit.
- [ ] Remote v1 Consumer E2E passes on the exact release-candidate commit.
- [x] Clean-install verification remains part of CI.
- [x] Action metadata exists in `action.yml`.
- [x] Automatic rerun defaults to `false`.
- [x] Selective rerun defaults to `false`.
- [x] README contains minimal installation examples and permission guidance.
- [x] CHANGELOG and SECURITY policy are present.
- [x] Public Incident Replay is an explicit CI gate.
- [x] Public Incident Replay v4 covers 9 source-backed incidents from 9 repositories.
- [x] Replay contract is bidirectional and requires zero false ALLOW / zero false BLOCK at full corpus coverage.
- [x] Terminal runner-shutdown evidence remains conservative unless independent high-specificity runner-origin evidence exists.
- [x] Authenticated runner-loss annotation fallback binds check-run ID, job name, head SHA, conclusion, app identity, and failure annotation.
- [x] Missing or unauthorized Checks access fails closed.
- [x] Side-effect boundaries remain independent of evidence provenance.
- [x] Setup Doctor recommends and probes `checks: read` without performing writes.
- [x] Evidence-before-Action ActionRequest / AssumptionState / AuthorityGrant / Decision / ExecutionReceipt contracts are present.
- [x] Canonical JSON, temporal, context, assumption, authority, and governed-action conformance tests are present.
- [x] Historical Flakiness evidence remains shadow-only and cannot change production authorization.
- [x] Decision Experience v1 remains descriptive-only and cannot grant retry authority.
- [x] Fleet Report v1 remains report-only and cannot mutate workflow runs or claim unsupported savings.
- [x] Setup Doctor emits copy-ready activation YAML only after READY and never writes it into the target repository.
- [x] Public zero-install annotation fallback preserves exact check-run/job/head/conclusion/app binding and cannot mutate the target repository.
- [x] Causal Dominance remains research-only and is not imported by production retry entrypoints.
- [x] Two independent real Causal Dominance positive controls remain pinned: SWC and pipx.
- [ ] Third independent Causal Dominance positive control. This is **not a blocker for v1.4.1** because the feature remains disabled in production.
- [x] MIT License is present.

## v1.4.1 production scope

This patch keeps the v1.4.0 authorization model intact and improves the zero-install activation path. When public job-log download is unavailable, `INPUT_PUBLIC_READ_ONLY=true` may consume publicly readable GitHub Checks metadata and annotations through the same exact binding and runner-loss signal requirements used by the authenticated fallback. No target-repository credential is forwarded and no write authority is added.

The following remain outside production retry authority:

- Causal Dominance override;
- historical flakiness as an authorizing signal;
- research-only classifier promotion experiments.

## Tagging plan

1. Merge the v1.4.1 release-preparation pull request only after its required checks are green.
2. Confirm the post-merge `main` CI run is green.
3. Create the immutable `v1.4.1` release tag from that exact green `main` commit.
4. Move the stable major tag `v1` to the same commit.
5. Publish release notes from `CHANGELOG.md`.
6. Run the permanent published-`@v1` smoke path.
7. Keep `auto-rerun: 'false'` and `selective-rerun: 'false'` in first-run examples; write behavior remains explicit opt-in.

## Post-release smoke test

The repository contains a permanent consumer smoke test for the published moving major ref `@v1`.

1. Run **CI Retry Gate Release Smoke Fixture** manually.
2. The fixture intentionally ends in failure with a deterministic `TypeError`.
3. **CI Retry Gate v1 Release Smoke** starts automatically through `workflow_run`.
4. It consumes `achirothmane/workflow-failure-lab@v1` in report-only mode.
5. The smoke passes only when the released action reports:
   - `safe-to-rerun=false`
   - `rerun-triggered=false`
   - at least one failed job observed

The red fixture run is intentional; the verification workflow must be green. This tests the published `@v1` ref rather than the current `main` implementation.
