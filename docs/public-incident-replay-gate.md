# Public Incident Replay Gate v4

V4 keeps the mechanism-diverse V3 corpus and closes one evidence-availability gap:
GitHub can retain a failure annotation for a runner that disappeared even when the job log
blob was never uploaded.

The production decision path is now:

```text
job log available
    -> ordinary step-bound log provenance

job log unavailable
    -> authenticated GitHub Checks lookup
    -> exact job/check-run/head/app binding
    -> exact runner-loss failure annotation
    -> EvidenceBundle
    -> ALLOW / BLOCK
```

The annotation path is a fallback. It does not compete with or override ordinary log
evidence.

## Authorization boundary

A check annotation can contribute retry authority only when all of the following hold:

- the job log could not be acquired;
- an authenticated GitHub token is present;
- the workflow job contains a valid `check_run_url`;
- the fetched check-run id equals that URL's id;
- check-run name equals the workflow job name;
- check-run head SHA equals the workflow job head SHA;
- both job and check run are completed failures;
- the check run belongs to the `github-actions` app;
- the annotation level is `failure`;
- the annotation begins with GitHub's runner-loss message;
- the job does not cross a side-effect boundary;
- the retry-attempt policy still permits another execution.

A missing or unreadable Checks endpoint, binding mismatch, non-GitHub Actions check,
warning-level annotation, or merely similar prose remains fail-closed.

## V4 public ground truth

The PRQL control from V3 is intentionally versioned:

- V3: runner loss was known retrospectively, but missing decision-time provenance meant
  expected `BLOCK`.
- V4: the same incident is replayed with the surviving GitHub Actions check annotation
  bound to the exact job/check/head, so it becomes expected `ALLOW`.

The other eight public incidents keep their prior decisions.

V4 therefore contains nine incidents across nine repositories:

- five expected `ALLOW`;
- four expected `BLOCK`.

The corpus still requires:

```text
false ALLOW = 0
false BLOCK = 0
coverage = 100%
```

## Why the annotation is not treated as root-cause proof

"The hosted runner lost communication" describes the control plane's observation. It does
not prove whether the runner process died because of infrastructure, CPU/memory
starvation, or network isolation.

CI Retry Gate uses that exact signal only for the already-supported bounded
`RUNNER_INFRA` retry class. It does not rewrite the retrospective cause family and does
not weaken the side-effect or attempt gates.

## Permission behavior

Reading check-run annotations uses GitHub's Checks API. Consumers should grant
`checks: read` in addition to `actions: read`. If that permission is absent, the
fallback records evidence unavailability and blocks rather than silently degrading into
an ALLOW.

## Replay

Run:

```bash
python public_incident_replay.py --check
```

V4 replays the PRQL control through the annotation-specific production helper instead of
copying issue text into the ordinary job-log path.
