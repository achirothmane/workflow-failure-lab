# Examples

This directory contains both **copy-ready product examples** and lower-level fixtures used by tests and validation.

If you are evaluating CI Retry Gate for the first time, start with:

1. [report-only.yml](report-only.yml) — install the stable action without granting rerun authority.
2. [setup-doctor.yml](setup-doctor.yml) — validate configuration before enabling writes.
3. [historical-run-trial.yml](historical-run-trial.yml) — analyze historical runs.

The JSON files in this directory are evidence / behavior fixtures. They are useful for development and validation, but they are not the primary adoption path.

For the shortest end-to-end path, see [docs/quickstart.md](../docs/quickstart.md).
