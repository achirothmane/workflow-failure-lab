# EASL conformance snapshot

This directory contains the canonical subject-state binding vectors copied from:

- repository: `achirothmane/easl`
- path: `conformance/subject_state_binding.json`
- source commit: `8e6a601be100aa54310f3bd94296af5a649a5f0d`

The snapshot is vendored intentionally so CI Retry Gate does not add a network dependency to its test or runtime path.

When EASL changes this conformance contract, update this snapshot explicitly in a reviewed pull request and run the Python compatibility suite before adopting the new contract.
