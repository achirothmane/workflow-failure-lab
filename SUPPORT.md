# Support

CI Retry Gate is an open-source GitHub Action for evidence-backed retry decisions.

## Before opening an issue

If you are evaluating the product, start with the zero-install public analysis flow in the README. It lets you test one public GitHub Actions failure without installing the action or granting write access.

If you are installing CI Retry Gate, run the Setup Doctor first. It reports `READY`, `WARN`, or `BLOCKED` and provides concrete fixes before you enable any write behavior.

## Bug reports

Open a GitHub Issue in this repository and include:

- the CI Retry Gate version or ref you used;
- the target workflow name;
- the workflow run ID and attempt number when relevant;
- the observed `ALLOW`, `BLOCK`, or `UNKNOWN` result;
- what you expected instead;
- any redacted logs or screenshots that are safe to share.

Do not post repository secrets, tokens, credentials, or private logs.

## Public-run analysis

For a public repository, use the **Analyze a public GitHub Actions failure** issue template. This path is read-only: it does not modify the target repository and does not trigger a rerun.

## Security issues

Do not open a public issue for a security vulnerability.

Use the process described in [SECURITY.md](SECURITY.md).

## Scope

Support covers CI Retry Gate behavior, setup, evidence interpretation, and documented integrations.

It does not include debugging unrelated application failures or guaranteeing that a failed third-party workflow is safe to rerun when the required evidence is unavailable.
