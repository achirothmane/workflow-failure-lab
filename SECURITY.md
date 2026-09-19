# Security Policy

## Supported version

Security fixes are applied to the latest release and to `main`.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose credentials, bypass retry-safety boundaries, trigger unintended workflow execution, or leak private CI logs.

Use GitHub's private vulnerability-reporting / Security Advisory flow for this repository when available. If that flow is unavailable, open a minimal public issue asking for a private contact channel without including exploit details, secrets, private logs, or credentials.

## Security boundaries

CI Retry Gate is intentionally fail-closed:

- automatic rerun is off by default;
- rerun authority requires transient classification, execution provenance, attempt limits, and no detected side-effect boundary;
- research and benchmark modes are read-only;
- Causal Dominance research does not alter production classification or retry authority;
- GitHub tokens should use the minimum permissions required by the selected mode.

Never paste long-lived tokens or repository secrets into issue bodies, workflow logs, benchmark inputs, or support messages.
