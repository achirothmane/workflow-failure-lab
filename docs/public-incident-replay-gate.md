# Public Incident Replay Gate v2

The Public Incident Corpus is useful only if production decision logic is forced to
survive it in both directions.

The gate replays every admitted incident through the same production path used by
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

## Bidirectional authorization contract

V1 contained three denial-side controls. V2 keeps those controls and adds three
source-backed positive controls from independent repositories.

The required property is now:

```text
known unsafe/ambiguous incident  => BLOCK
known bounded transient incident => ALLOW
```

The gate fails on either a false `ALLOW` or a false `BLOCK`.

## V2 positive controls

| Repository | Run | Failed job | Failure evidence | Rerun ground truth | Expected |
|---|---:|---|---|---|---|
| alunduil/alunduil-chezmoi | 30240791215 | Run pre-commit hooks | curl connection reset during Install lychee | same job succeeded in attempt 2 | `ALLOW` |
| vtmocanu/uzi | 33985176395 | lint-controller | curl connection reset during lint/download path | same job succeeded in attempt 2 on the same SHA | `ALLOW` |
| docker/compose | 35155815118 | relay-image-test / build (linux/amd64) | repeated Docker Hub 502 responses inside Build | same job succeeded in attempt 2 | `ALLOW` |

For all three controls, the replay uses source-backed failed-job identity and failed-step
timing so execution provenance must pass exactly as it does in production.

## V2 negative controls

The original three controls remain:

- GEOPHIRES-X #526;
- deck-streak #439;
- 1-bit-bridge #1098.

They demonstrate that a terminal runner-shutdown / exit-143 symptom cannot independently
prove runner infrastructure causality.

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

The replay fixtures separate decision-time evidence from retrospective ground truth.

- Positive controls preserve public failed-job identity and failed-step timing.
- Log excerpts contain evidence available during the failed attempt.
- The later successful rerun proves recovery, but its success text is not injected into
  the failure log.
- Negative controls retain their earlier conservative replay scaffolding where exact
  upstream metadata is not required to prove the BLOCK invariant.
- Retrospective root-cause knowledge is never injected into a failure log merely to make
  the classifier reach the expected answer.

This keeps the gate from learning from information that would not have been available
at authorization time.

## Next expansion

V2 proves both sides with six incidents across six repositories. The next useful
expansion is mechanism diversity rather than raw volume: DNS failures, explicit hosted
runner loss, rate limiting, TLS handshake timeout, and additional dependency 5xx cases.
