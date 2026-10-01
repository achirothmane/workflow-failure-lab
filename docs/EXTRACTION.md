# Standalone extraction

The repository-ready source is extracted from the tested `releaseguard/` directory in `achirothmane/workflow-failure-lab`. Runtime code, workflows, configuration, database schema, browser code, and all existing tests are unchanged.

## Original proof

- Source commit: `2a85d680d33d02778d640feeb5a8aa2211b463a7`.
- [Actual n8n and adversarial validation run](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36768732791).
- [Tested artifact](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36768732791/artifacts/11122762266).
- Artifact archive SHA-256: `1150c5cfb374f267768567eb37bed286ce6fcbc1e6690b345bef0bf871bbbb80`.
- The archive digest and all 45 files listed in its manifest were verified before extraction.

The preserved baseline manifest and JSON results are in `docs/baseline/`; screenshots from the original run are in `docs/images/`. Those files describe the original build, not a later execution. Runtime logs and disposable credential files are excluded from the source repository.

`extraction-provenance.json` records SHA-256 values for the 28 unchanged runtime, workflow, test, configuration, dependency, and supporting files. The baseline manifest uses paths relative to the original package.

## Extraction changes

- Move the standalone product source to the repository root.
- Activate the existing standalone CI recipe as `.github/workflows/ci.yml` on branch pushes and pull requests.
- Commit the tested dependency lockfile and use `npm ci --ignore-scripts` in CI, and `npm ci --omit=dev --ignore-scripts` in Docker.
- Explicitly create the generated evidence directory before starting the CI sidecar.
- Ignore generated test evidence and ZIP packages; preserve selected original proof under `docs/`.
- Update the README, add this provenance note, and add the changelog.

Standalone CI retains every existing policy/security, HTTP/PostgreSQL, actual n8n, and browser-evidence check. Extraction readiness requires a successful run for the exact extraction commit; the original green run alone is insufficient.

## Next installation work

1. Make workflow and credential installation repeatable, and verify it from a fresh operator account.
2. Detect changes to registered published Stable/Candidate workflows before promotion.
3. Define response-cache retention and evidence archival, then measure sustained throughput and a longer soak.

The production scope remains synchronous read-only JSON transforms with one ReleaseGuard controller. This extraction does not add side-effect rollback, multi-controller operation, n8n Cloud compatibility, or evidence of paid adoption.
