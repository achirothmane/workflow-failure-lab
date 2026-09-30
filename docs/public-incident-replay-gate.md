# Public Incident Replay Gate v1

The Public Incident Corpus is useful only if production decision logic is forced to
survive it.

This gate replays every admitted V1 incident through the same production path used by
CI Retry Gate:

```text
failure log + failed-job metadata
        ↓
assess_job
        ↓
EvidenceBundle
        ↓
build_ci_retry_decision
        ↓
ALLOW / BLOCK
```

## What it prevents

A classifier rule may look locally better while reintroducing a known dangerous
authorization error. The replay gate turns public incidents into permanent regression
constraints.

For the initial corpus, all three incidents are **BLOCK** controls. Each publicly
documented case ended with a runner-shutdown symptom that was later associated with
workload/resource behavior rather than independently proven runner infrastructure.

The safety property is:

```text
known BLOCK incident
    ⇒ production replay must not return ALLOW
```

Any false `ALLOW` fails the gate.

## Metrics

The replay command reports:

- corpus coverage;
- false `ALLOW` count;
- false `BLOCK` count;
- evidence decisions that remain `UNKNOWN`;
- the production classification/confidence for every replayed case.

Run locally:

```bash
python public_incident_replay.py --check
```

The command exits non-zero when corpus coverage is incomplete or a replay decision
disagrees with its expected authorization.

## Fixture integrity

The replay fixtures deliberately separate source-backed incident evidence from local
execution scaffolding.

- Log excerpts and their interpretation are tied to the public incident source.
- Synthetic job IDs/timestamps used only to exercise the deterministic gate are not
  claimed to be upstream GitHub metadata.
- Retrospective root-cause knowledge is **not injected into the failure log** merely to
  make the classifier succeed.

This avoids training the gate on information that would not have been available at the
decision point.

## Current limitation

V1 is denial-side coverage: the three admitted incidents are expected `BLOCK` cases.
The implementation already tracks false `BLOCK`, but that metric becomes meaningful
only after source-backed positive controls with an expected `ALLOW` decision are
admitted.

The next corpus expansion should therefore add independently validated transient
recoveries as positive controls, while retaining the existing authority and provenance
requirements.
