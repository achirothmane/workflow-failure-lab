# v1 Release Readiness

This checklist covers the CI Retry Gate v1 release line. The current release target is `v1.1.0`.

## Required before tagging

- [x] Repository CI passes on `main`.
- [x] Clean-install verification passes.
- [x] Action metadata exists in `action.yml`.
- [x] Automatic rerun defaults to `false`.
- [x] Selective rerun defaults to `false`.
- [x] README contains a minimal installation example and permission guidance.
- [x] CHANGELOG and SECURITY policy are present.
- [x] Causal Dominance remains research-only and is not imported by the production retry entrypoints.
- [x] Two independent real Causal Dominance positive controls are pinned: SWC and pipx.
- [ ] Third independent Causal Dominance positive control. This is **not a blocker for v1 release** because the feature remains disabled in production.
- [x] MIT License added for the public v1 release.
- [x] EvidenceBundle is persisted before authorization and verified by SHA-256 across a separate process boundary.

## v1 production scope

The public v1 release includes the conservative retry gate, provenance checks, side-effect boundaries, history/fingerprint analysis, selective rerun, policy learning, shadow mode, benchmark mode, and research diagnostics already wired into the action.

The causal-dominance override is explicitly excluded from production scope. It remains a research feature until its separate evidence threshold is met.

## Tagging plan

1. Merge the release-readiness pull request.
2. Confirm the post-merge CI run is green.
3. Create the `v1.1.0` release tag from the exact green `main` commit.
4. Create/update the moving major tag `v1` to the same commit so users can pin:
   `achirothmane/workflow-failure-lab@v1`.
5. Publish release notes from `CHANGELOG.md`.
6. Keep `auto-rerun: 'false'` in the first-run example; users opt into write behavior explicitly.


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
