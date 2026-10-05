# Internal validation

This directory contains release, regression, and compatibility validation assets that exercise CI Retry Gate without becoming part of its stable runtime API.

## Public incidents

`validation/public_incidents/` contains the source-backed incident corpus and replay gate used by CI to verify that known ALLOW/BLOCK cases remain stable.

The validation layer may import product runtime modules. Product runtime modules should not depend on validation packages.
