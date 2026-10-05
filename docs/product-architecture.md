# CI Retry Gate — product architecture

This document describes the **product shape** of CI Retry Gate. It is intentionally different from a file-by-file research history.

The public product is built around one workflow:

```text
Failed GitHub Actions run
          |
          v
   Evidence collection
          |
          v
 Failure + context analysis
          |
          +---- provenance
          +---- exact failed execution
          +---- side-effect risk
          +---- retry limits
          +---- stale/contradictory evidence
          +---- historical evidence (when available)
          |
          v
     Decision boundary
      /      |      \
   ALLOW   BLOCK   UNKNOWN
      |       |        |
      |       |        +--> investigate / gather evidence
      |       +-----------> keep CI red / stop retry loop
      +-------------------> bounded retry is eligible

          optional write path
                 |
                 v
        explicit rerun behavior
```

## Public product surface

A user should be able to understand CI Retry Gate through four surfaces:

| Surface | Purpose |
|---|---|
| `@v1` GitHub Action | Evaluate a failed workflow run |
| Public-run analyzer | Try the decision logic without installing |
| Setup Doctor | Check configuration before enabling write behavior |
| Machine-readable outputs | Integrate decisions with CI automation |

Everything else supports those surfaces.

## Read path and write path are separate

The default adoption path is read-only.

```text
observe failure
    ↓
collect evidence
    ↓
evaluate
    ↓
report decision
```

Only after the repository is configured intentionally can a write-capable path be enabled.

That separation is part of the product design: evaluation should be useful even when the user never grants rerun authority.

## What is stable

The stable user-facing contract is the v1 GitHub Action surface and its documented behavior.

Research code, validation harnesses, benchmark utilities, replay fixtures, and internal experiments are **not** the adoption surface and should not be treated as public API merely because they live in the repository.

## Why the repository contains more than the product surface

The project grew through repeated validation against failure cases, historical runs, recovery evidence, and controlled fixtures.

Those assets remain valuable for:

- regression testing;
- release confidence;
- falsification of unsafe assumptions;
- benchmarking;
- reproducing edge cases.

The productization goal is to keep that depth **behind** a simple user journey rather than expose the entire research history as the first thing a new user must understand.

## Release confidence

The product is exercised through:

- repository CI;
- compatibility tests;
- a remote stable-interface consumer;
- public incident replay;
- clean-install checks;
- release smoke tests.

See the main [README](../README.md) for the current release-facing claims and [technical-reference.md](technical-reference.md) for implementation detail.
