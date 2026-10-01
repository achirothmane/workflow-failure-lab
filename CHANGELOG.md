# Changelog

## 0.1.0 — 2026-10-01

Initial standalone extraction of the verified ReleaseGuard build.

- Stable/Candidate routing with configurable progressive canaries and deterministic release decisions.
- Measured failures and latency, input/output contracts, read-only fallback, automatic rollback, and decision evidence.
- PostgreSQL routing transactions, admission fences, encrypted request replay, and an alert outbox.
- Importable n8n workflows, an operations dashboard, Docker Compose, Setup Doctor, and setup/demo documentation.
- Existing adversarial suites and actual n8n 2.41.4 production-webhook validation retained in standalone CI.
- Tested dependency lockfile included for reproducible installation and container builds.

See [extraction provenance](docs/EXTRACTION.md) and [validation scope](docs/validation.md). This version is a release candidate for a controlled pilot.
