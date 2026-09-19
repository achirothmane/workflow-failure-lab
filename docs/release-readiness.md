# v1 Release Readiness

This checklist is the release gate for CI Retry Gate `v1.0.0`.

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
- [ ] License choice. No new license is granted by this release-prep change; repository usage remains subject to the repository owner's chosen licensing terms.

## v1 production scope

The public v1 release includes the conservative retry gate, provenance checks, side-effect boundaries, history/fingerprint analysis, selective rerun, policy learning, shadow mode, benchmark mode, and research diagnostics already wired into the action.

The causal-dominance override is explicitly excluded from production scope. It remains a research feature until its separate evidence threshold is met.

## Tagging plan

1. Merge the release-readiness pull request.
2. Confirm the post-merge CI run is green.
3. Create release tag `v1.0.0` from that exact green `main` commit.
4. Create/update the moving major tag `v1` to the same commit so users can pin:
   `othy19904-eng/workflow-failure-lab@v1`.
5. Publish release notes from `CHANGELOG.md`.
6. Keep `auto-rerun: 'false'` in the first-run example; users opt into write behavior explicitly.
