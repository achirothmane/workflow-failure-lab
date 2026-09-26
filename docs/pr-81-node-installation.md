# PR #81: Node fixture installation failure

Investigated head: `ce93634e142bee119a2e9d3522a8c38dbda09eb0`.

## Root cause

The smallest reproduced trigger is an otherwise empty project with:

```json
{"private":true,"devDependencies":{"vitest":"5.0.1"}}
```

With npm **10.8.2**, the resolver used by the failing CI jobs, this command fails:

```sh
npm install --ignore-scripts --no-audit --no-fund --package-lock=false
```

The failure is in npm's Arborist dependency resolver, before test execution:

```text
TypeError: Cannot read properties of null (reading 'edgesOut')
at #loadPeerSet (.../@npmcli/arborist/lib/arborist/build-ideal-tree.js:1286:38)
```

That line reads `node.parent.edgesOut`. A diagnostic-only copy of npm, instrumented
without suppressing the exception, identifies the detached node as `vitest@5.0.2`
while visiting its optional `@vitest/browser-preview@5.0.2` peer. The observed
resolution trace traverses `vite@8.3.1`, its optional devtools peers, and
`@vitejs/devtools-vitest@0.7.6` (optional peer `vitest: "*"`). npm selects a newer
Vitest peer candidate while also resolving the fixture's exact 5.0.1 peer family.
The old resolver then dereferences that candidate's null parent.

Both original fixture manifests declared Jest, jest-junit, and Vitest together.
`npm install jest ... --no-save` still resolves the manifest's other dependencies,
including Vitest. This exposes Jest jobs to the same failure. A Jest/Vitest
interaction is **not required**: Vitest alone reproduces it. Splitting the
environments alone is therefore insufficient; the resolver must also be fixed.

## Controlled evidence

Local clean-directory experiments used Node 24.19.0 and the npm versions below.
The original GitHub jobs reproduce the crash on Node 20.20.2 / npm 10.8.2.
No cache clearing, retries, peer-check bypass, or test suppression was used.

| Manifest dependencies | npm | Result |
| --- | --- | --- |
| Jest 30.5.2 + jest-junit 17.0.0 | 10.8.2 | Install succeeds |
| Vitest 5.0.1 only | 10.8.2 | `edgesOut` failure |
| Jest 30.5.2 + Vitest 5.0.1 | 10.8.2 | Same failure |
| All three original dependencies | 10.8.2 | Same failure |
| Vitest 5.0.1 only | 11.20.0 | Install succeeds |
| All three original dependencies | 11.20.0 | Install succeeds |
| Vitest 5.0.2 only (diagnostic comparison) | 10.8.2 | Install succeeds |

The fix keeps Vitest **5.0.1** in the smoke and remote fixtures. The 5.0.2
comparison is evidence about peer resolution, not a dependency upgrade.

GitHub evidence:

- [Original head smoke installation](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36209067405/job/108311663407).
- [Original head Jest compatibility installation](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36209067446/job/108311663493).
- [Original head remote Jest/Vitest installations](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36209067294).
- [Clean-directory full-manifest probe](https://github.com/achirothmane/workflow-failure-lab/actions/runs/36207935305/job/108308322574): trivial package, Jest alone, and reporter alone install; copying only the fixture manifest to `/tmp` reproduces the crash.

## Diagnostic changes versus the original defect

The two combined manifests already existed on the PR base and were unchanged by
the diagnostic commits. There were no tracked npm lockfiles or `.npmrc` files.
The Python consolidation/regression changes are separate and remain intact.

- `5b0d4ee` through `5d97e7c`: lockfile bypass and Node 20 experiments do not fix the crash. Vitest 5.0.1 declares Node `^22.12.0 || ^24.0.0 || >=26.0.0`; Node 20 is outside its supported range.
- `f0f28a0` through `a3b773d`: temporary package probes provide useful controls; they are not production installation steps.
- `0246295`: sequential Jest and Vitest commands still share one manifest and dependency environment.
- `e134a31`: introduced a literal `\n` into the compatibility shell script; `ce93634` repaired the newline but left a repository-relative Jest binary path after changing directories. That latent path failure is independent of `edgesOut`.

## Durable changes

1. Restore Node 22 and use exact npm 11.20.0 in every Node job.
2. Keep Jest + jest-junit in each existing `node/package.json`; move only the Vitest dependency declaration into `node/vitest/package.json`. Test files remain unchanged.
3. Commit a lockfile for each of the four dependency environments. Smoke and remote jobs use `npm ci --ignore-scripts --no-audit --no-fund`.
4. Install compatibility majors into their framework's own fixture and run the local executable. Preserve the existing latest-patch-per-major coverage; only this matrix deliberately bypasses the pinned fixture locks.
5. Use the correct fixture-relative executable paths. Retain all block, JUnit extraction, quarantine-count, regression, and remote `@v1` assertions.

Installation steps remain fatal. Existing `continue-on-error` settings apply only
to intentional failing-test probes whose outcomes are subsequently asserted.

## Validation

Local validation used Node **22.23.3** and npm **11.20.0**:

- All four `npm ci` installations succeeded. The Jest locks contain no Vitest;
  the Vitest locks contain no Jest or jest-junit.
- Eight Node cases passed both required outcomes: pinned smoke Jest/Vitest,
  remote-consumer Jest/Vitest, Jest 29.7.0 and 30.5.2, and Vitest 4.1.11 and 5.0.2.
- Each block run exited 1 with one blocking assertion failure; each ACTIVE run
  exited 0 with zero blocking failures and one quarantined assertion failure.
  Both reports retained the real failing testcase. Consumer IDs were derived
  using the existing independent consumer extractor.
- Local remote-consumer verification used the checked-out `@v1` product at
  `0225c4e015b77ca649ede1e7bea11b162a1282f3`. GitHub remote action resolution and
  artifact upload remain covered by the unchanged remote workflow assertions.
- `pytest -q`: **339 passed**. Full unittest discovery: **17 passed**.
- Release-readiness verifier passed.
- All 32 existing workflow verification/extraction/regression steps and all
  matrix cells were preserved. No product code or testcase assertion changed.
- YAML parsing and `git diff --check` passed.
