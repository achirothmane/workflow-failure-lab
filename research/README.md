# Internal research

This directory contains **validation, falsification, and research-only code** that supports CI Retry Gate but is not part of the stable product adoption surface.

The stable user-facing surface remains:

- the `@v1` GitHub Action;
- the public-run analyzer;
- Setup Doctor;
- documented machine-readable outputs.

## Causal dominance

`research/causal_dominance/` contains bounded experiments used to test whether specific causal evidence is strong enough to change conclusions under controlled conditions.

These modules may change as research evolves. They are not public API and should not be imported by external users.

Research code may import stable product modules for measurement or replay. Stable product runtime code should not depend on research packages for ordinary operation.
