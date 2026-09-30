# Public Incident Replay Gate v3

The Public Incident Corpus is useful only if production decision logic is forced to
survive real incidents in both directions and across more than one failure mechanism.

The gate replays every admitted incident through the same production path used by
CI Retry Gate:

```text
failure evidence + failed-job metadata
        ↓
assess_job
        ↓
EvidenceBundle
        ↓
build_ci_retry_decision
        ↓
ALLOW / BLOCK
```

## V3 contract

V2 established a bidirectional baseline with three expected `ALLOW` and three expected
`BLOCK` cases. V3 keeps those six and adds three mechanism-diverse controls.

The required property remains:

```text
known unsafe / insufficient-evidence incident => BLOCK
known bounded transient incident              => ALLOW
```

A known root cause does not automatically create execution authority. Evidence must also
be bound to the failed execution.

## New V3 controls

| Repository | Mechanism | Ground truth | Expected |
|---|---|---|---|
| alethialabs-io/alethialabs | `dial tcp ... network is unreachable` during Helm repository fetch | same job succeeded on attempt 2 | `ALLOW` |
| PRQL/prql | GitHub hosted runner lost communication | attempt 2 succeeded, but failed job has no uploaded log blob / failed-step metadata | `BLOCK` |
| HiromiShikata/npm-cli-github-issue-tower-defence-management | GitHub API rate-limit failure | same job/step failed again on attempt 2 | `BLOCK` |

The PRQL case is deliberately important: retrospective diagnosis says runner loss, but
the current production evidence path cannot bind the annotation to a failed step because
the runner died before usable execution provenance was retained. V3 therefore preserves
fail-closed behavior rather than treating later knowledge as authority.

The rate-limit case is the opposite warning: dependency-shaped failures are not
automatically transient enough to rerun. Immediate recurrence on the same job identity is
ground truth against blind retry promotion.

## Full V3 population

V3 contains nine public incidents across nine repositories:

- four positive transient controls;
- five negative / insufficient-authority controls;
- connection reset, external HTTP 5xx, network unreachable, runner shutdown ambiguity,
  hosted-runner loss, workload resource pressure, and persistent rate-limit behavior.

## Metrics

The replay command reports:

- corpus coverage;
- false `ALLOW` count;
- false `BLOCK` count;
- evidence decisions that remain `UNKNOWN`;
- production classification/confidence and provenance for every replayed case.

Run locally:

```bash
python public_incident_replay.py --check
```

The command exits non-zero on incomplete coverage or any authorization disagreement.

## Evidence integrity

- Positive controls use source-backed failed-job IDs and failed-step timing.
- Successful reruns are ground truth; their success text is not injected into failure logs.
- Retrospective diagnosis is never used to manufacture decision-time provenance.
- A known transient mechanism may still be expected `BLOCK` when the evidence needed to
  authorize execution is unavailable.
- A repeated failure remains evidence against automatic rerun even when its broad category
  looks transient.

## Next engineering boundary

The next useful capability is an authenticated **runner-annotation evidence path**. GitHub
can retain a hosted-runner-loss annotation even when the job log blob is missing. That
signal should remain non-authorizing until CI Retry Gate can ingest it with explicit
source identity, permission handling, and provenance semantics rather than copying issue
text into the classifier.
