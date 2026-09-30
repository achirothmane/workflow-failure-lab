# Runner shutdown ground truth

This note records public cases where GitHub Actions ended with the terminal message
`The runner has received a shutdown signal` but the root cause was not proven to be
runner infrastructure.

The purpose is classifier falsification, not copying repository-specific fixes.

## Cases

### GEOPHIRES-X #526

Observed: the Python 3.9 job reached 100% passing tests, then GitHub reported a runner
shutdown and exit code 143.

Resolution: the project reduced three Reservoir `lru_cache` max sizes from 1024 to
256. The change was described as limiting memory usage and was incorporated into the
3.18 patch release.

Sources:
- https://github.com/NatLabRockies/GEOPHIRES-X/issues/526
- https://github.com/Bernard-Ngu/GEOPHIRES-X/pull/3
- https://github.com/NatLabRockies/GEOPHIRES-X/pull/527

### deck-streak #439

Observed: mutation-test shards ended with the same runner shutdown message.

Ground truth: the same shard repeatedly died on the same runaway mutant. The mutant
made loop progress zero while continuing to allocate memory.

Resolution: execute mutation tests inside a bounded systemd memory scope with swap
forbidden and record a memory-cap kill as a named failure instead of losing the
runner.

Source:
- https://github.com/RexRenatus/deck-streak/issues/439

### 1-bit-bridge #1098

Observed: a nightly fuzz leg repeatedly ended with runner shutdown / exit 143 and no
crash artifact.

Ground truth: a crafted FLAC input could cause a multi-gigabyte allocation and
out-of-memory failure.

Resolution: add an allocation guard and run fuzz workers under an address-space
limit using `prlimit`, so the worker fails and preserves a diagnostic crasher
instead of exhausting the runner.

Source:
- https://github.com/acoseac/1-bit-bridge/pull/1098

## Classifier implication

The common observation is a terminal symptom, not a causal mechanism:

`runner shutdown / exit 143 != independent proof of RUNNER_INFRA`

CI Retry Gate therefore requires independent runner-origin evidence before this
symptom can participate in a high-confidence transient classification.

Policy invariant:

`RUNNER_SHUTDOWN_TERMINAL_SYMPTOM_ONLY => NO_HIGH_CONFIDENCE_TRANSIENT => BLOCK`

Examples of stronger independent runner evidence include loss of communication with
the GitHub runner service or an explicit hosted-runner unavailability/failure signal.

Repository-specific memory fixes are not transplanted into CI Retry Gate. Their
validated outcomes become ground-truth counterexamples that constrain the generic
decision logic.
