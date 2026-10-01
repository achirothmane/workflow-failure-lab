# External Activation Gate v1

This gate tests whether CI Retry Gate can deliver useful evidence to a maintainer before any write behavior is enabled.

It is an adoption experiment, not a new authorization layer.

## Funnel under test

```text
Discover
→ Public historical failure
→ Decision at a glance
→ Next action
→ Setup Doctor
→ Copy-ready report-only activation
→ Repeated use
```

## Stage A — zero-install external failure

Target:

- Repository: `Bernard-Ngu/GEOPHIRES-X`
- Workflow run: `36012993291`
- Historical attempt: `2`
- Target repository modification: none
- Target token requested: none
- Rerun triggered: none

The v1.4.0 rerun of the public analysis produced:

- decision: `BLOCK`
- evidence: `CONTRADICTED`
- next action: `STOP_RETRY_LOOP`
- failed runtime represented by the decisive recurrent job: `13.50 min`
- rerun-eligible jobs: `0`
- blocked jobs: `1`
- next-attempt recurrence preserved even though a later attempt eventually succeeded
- historical recovery evidence remained supporting-only and did not authorize execution

This proves that the new Decision Experience can turn an external public run into a concise operator decision without target-repository writes.

## Activation blocker exposed

The same trial also exposed a real zero-install evidence boundary:

```text
GET /repos/Bernard-Ngu/GEOPHIRES-X/actions/jobs/107760608854/logs
→ HTTP 403
→ "Must have admin rights to Repository."
```

The product correctly failed closed to `EVIDENCE_UNAVAILABLE` rather than inventing a failure cause.

That is safe, but it can reduce the usefulness of the zero-install path. We therefore need to establish exactly which public GitHub evidence endpoints remain readable without target-repository credentials before changing product behavior.

## Stage B — public evidence access probe

The workflow `.github/workflows/public-evidence-access-probe.yml` probed the same external run without a target token and established:

| Evidence endpoint | Result |
|---|---:|
| repository metadata | HTTP 200 |
| workflow-run metadata | HTTP 200 |
| historical-attempt jobs | HTTP 200 |
| check-run metadata | HTTP 200 |
| check-run annotations | HTTP 200 |
| job logs | HTTP 403 |

This isolates the activation gap precisely: public job-log download is unavailable, but GitHub's check-run and annotation evidence remains publicly readable.

The product change in this gate therefore allows `INPUT_PUBLIC_READ_ONLY=true` to use those public check annotations through the same exact-binding checks already required for authenticated annotation evidence. Installed mode remains authenticated. Outside public-read-only mode, a missing token still fails closed.

The probe also executes the public-read-only analysis end-to-end and asserts that the product no longer reports “requires a GitHub token” when the public annotation path is available.

The probe does not write to the external repository and does not treat an unavailable or ineligible annotation as authorization.

## Acceptance criteria

External Activation Gate v1 passes technically when:

1. a public external failure produces a deterministic Decision Experience result;
2. the target repository is not modified;
3. no target-repository credential is required for the zero-install trial;
4. inaccessible evidence remains explicit rather than inferred;
5. Setup Doctor can later produce a copy-ready report-only configuration for an installing maintainer;
6. value metrics do not claim counterfactual savings without evidence.

Human adoption is a separate gate: an independent maintainer must choose to run or install the product without direct engineering assistance from this repository's owner.

## Stop rule

Do not add another classifier or authorization feature merely to improve activation metrics.

If activation fails, first identify the failing funnel step:

```text
Discover → Try → Understand → Activate → Reuse
```

Only build a product change when a concrete failure at one of those steps justifies it.
