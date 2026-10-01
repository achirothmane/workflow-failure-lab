# Public Incident Replay Gate v5

V5 keeps the authenticated GitHub Checks fallback introduced in V4 and adds two held-out negative controls for persistence and provenance.

The production decision path remains:

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

The annotation path is a fallback. It does not compete with or override ordinary log evidence.

## Authorization boundary

A check annotation can contribute retry evidence only when all of the following hold:

- the job log could not be acquired;
- an authenticated GitHub token is present;
- the workflow job contains a valid `check_run_url`;
- the fetched check-run id equals that URL's id;
- check-run name equals the workflow job name;
- check-run head SHA equals the workflow job head SHA;
- both job and check run are completed failures;
- the check run belongs to the `github-actions` app;
- the annotation level is `failure`;
- the annotation begins with GitHub's runner-loss message.

That can establish `RUNNER_INFRA/high` with `CONFIRMED` execution provenance. It does **not** bypass independent authority gates such as side-effect detection or the maximum-attempt policy.

## V4 provenance control retained

The PRQL control remains versioned:

- V3: runner loss was known retrospectively, but decision-time provenance was unavailable.
- V4: the surviving GitHub Actions check annotation established exact job/check/head provenance.
- Final authorization remained `BLOCK` because the job identity contained a release-shaped side-effect boundary.

That distinction remains part of V5:

```text
better evidence can improve provenance
without granting execution authority
```

## V5 held-out controls

V5 adds two source-backed cases selected after the earlier gate versions:

1. `actions/runner-images#13719`: a GitHub-hosted runner reports `No space left on device` while writing its own worker diagnostic log before any workflow step executes. The reporter reproduces the failure across reruns and after switching runner labels. The replay remains `BLOCK` as a `RESOURCE_TIMEOUT`-class control rather than treating a runner-shaped symptom as guaranteed-useful retry authority.
2. `aws-cloudformation/cfn-lint#4296`: `aws/serverless-application-model` run `19517345578` records `[Errno -3] Temporary failure in name resolution` through all three in-step retries. GitHub's latest-attempt job list later shows the same `ubuntu-latest / 3.9` job identity succeeding as job `55876077959`, after failed job `55875798766`. The issue-preserved failure text has no runner timestamps or failed-step timing metadata, so retrospective recovery cannot manufacture decision-time provenance. The replay remains `BLOCK`.

V5 therefore contains eleven incidents across eleven repositories:

- four expected `ALLOW`;
- seven expected `BLOCK`.

The new boundary is:

```text
later recovery != prior authorization evidence
runner-shaped failure != guaranteed useful immediate retry
```

The corpus still requires:

```text
false ALLOW = 0
false BLOCK = 0
coverage = 100%
```

## Why the annotation is not treated as root-cause proof

`The hosted runner lost communication` describes the control plane's observation. It does not prove whether the runner process died because of infrastructure, CPU/memory starvation, or network isolation.

CI Retry Gate uses that exact signal only for the already-supported bounded `RUNNER_INFRA` class. It does not rewrite the retrospective cause family and does not weaken side-effect protection.

## Permission behavior

Reading check-run annotations uses GitHub's Checks API. Consumers should grant `checks: read` in addition to `actions: read`. If that permission is absent, the fallback records evidence unavailability and blocks rather than silently degrading into an ALLOW.

## Replay

Run:

```bash
python public_incident_replay.py --check
```

V5 replays all eleven controls through the production evidence and authorization path. The two V5 additions do not introduce a separate evaluator.
