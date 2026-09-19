# ADR-0009: Flaky Test Ownership and Triage Routing

Status: Accepted

## Context

Wave 8 made flaky-test evidence visible inside GitHub, but a developer still had to determine who owns the failing test before investigation could start.

Ownership must be derived conservatively. Test IDs are framework-specific and do not always map cleanly to source files, while JUnit may omit the `file` attribute entirely. Guessing an owner can route incidents to the wrong team and create more noise than value.

## Decision

Add an opt-in ownership-routing layer to Flaky Test Intelligence.

Resolution order for each test is:

1. use a JUnit `file` attribute only when all observed non-empty source paths for that test agree on one normalized path;
2. match that path against the repository's CODEOWNERS file from the exact analyzed revision;
3. when no CODEOWNERS owner can be resolved, fall back to an explicit test-ID glob map;
4. otherwise mark the test `UNOWNED`.

CODEOWNERS locations are searched in GitHub's standard order:

- `.github/CODEOWNERS`
- `CODEOWNERS`
- `docs/CODEOWNERS`

The last matching CODEOWNERS rule wins.

## Explicit fallback map

The default path is `.github/flaky-ownership.json` and uses version 1:

```json
{
  "version": 1,
  "rules": [
    {
      "test_pattern": "payments.*::*",
      "owners": ["@payments-team"],
      "route": "payments-ci"
    }
  ]
}
```

Rules use shell-style test-ID glob matching. The last matching explicit rule wins so later rules can intentionally refine broader rules.

## Safety boundaries

Ownership routing is presentation metadata only. It cannot:

- authorize a retry;
- activate, renew, or release a quarantine;
- open or assign an issue;
- mention or notify an owner automatically.

Owners are rendered as code spans in Markdown so a triage PR comment does not create GitHub mentions merely because ownership was resolved.

When JUnit reports multiple different source files for the same test ID, CODEOWNERS resolution is considered ambiguous and skipped. The explicit mapping may still resolve the test because it does not depend on the ambiguous file path.

If CODEOWNERS or the fallback map is malformed or cannot be read, the action warns and keeps the triage decision unchanged.

## Outputs

When `flaky-ownership-routing=true`, the action exposes:

- `flaky-owned-items`
- `flaky-unowned-items`
- `flaky-ownership-rules`
- `flaky-codeowners-path`

These outputs are observational only.

## Non-goals

Wave 9 does not automatically create issues, assign maintainers, post Slack messages, or page teams. Routing evidence must be validated first before any new write authority is added.
