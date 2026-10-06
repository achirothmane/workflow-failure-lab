## What changed?

<!-- Describe the user-visible or architectural change in a few sentences. -->

## Why?

<!-- What problem, failure mode, or adoption friction does this solve? -->

## Contract impact

- [ ] No `action.yml` input/output change
- [ ] No stable `@v1` behavior change
- [ ] No adapter contract change
- [ ] No retry/write-authority change
- [ ] Documentation updated where needed

If any box above cannot be checked, explain the compatibility impact and migration path.

## Verification

- [ ] `make test`
- [ ] Clean-install verification when imports/packaging changed
- [ ] Relevant compatibility or E2E coverage updated
- [ ] New failure boundary or regression case covered by a test

## Repository boundary

- [ ] Product runtime does not import `research/` or `validation/`
- [ ] Any moved module was classified by execution path, not by filename alone
- [ ] Root entry points invoked directly by Actions/adapters remain reachable

## Safety

- [ ] Missing/contradictory evidence still fails closed
- [ ] Side-effect blocking is not weakened
- [ ] Research/benchmark logic does not silently grant production authority
- [ ] No secrets, tokens, credentials, or private logs are included
