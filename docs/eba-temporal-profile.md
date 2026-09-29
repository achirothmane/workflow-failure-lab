# EBA temporal admissibility profile v1

Profile: `eba.temporal/v1`  
Artifact contract: `eba.integration/v0.1`

This profile repairs temporal admissibility without introducing a global clock service.
Authorizing validation receives an explicit evaluation instant. Finite validity is
half-open:

```text
not_before <= now < expires_at
```

At `expires_at`, the artifact is invalid. RFC3339 offsets that denote the same
instant are equivalent after UTC normalization. Wrong-type, naive, empty, or
malformed timestamps fail closed.

The normative accepted/rejected examples are in
`conformance/eba-temporal-v1.json`.

## Profile-specific absence rules

`AssumptionState.valid_until = null` is not a generic permanent lease. It is
permitted only when the producing profile explicitly uses a non-wall-clock
invalidation boundary and no finite required input has been erased. The CI retry
profile is state-bound to repository/run/attempt/head/workflow identity. The
generic assumption-gate projection now inherits the earliest finite supporting
evidence expiry.

`AuthorityGrant.expires_at` is finite and required. The CI retry profile issues
a five-minute local grant window and revalidates it at the actual rerun boundary.

`BudgetReservation.expires_at` is finite and may never outlive the budget
snapshot that authorized it. If the budget has no wall-clock expiry, the caller
must supply a finite reservation expiry.

The Aegis Kubernetes-drain profile is stricter than the generic assumption shape:
its mutation-bound AssumptionState requires a finite `valid_until`.

## Consumer compatibility

| Owner | Relevant vectors | Profile-specific rule |
|---|---|---|
| workflow-failure-lab | T01-T07, T11 | CI assumption may use explicit null wall-clock expiry only with its exact state-bound action context; AuthorityGrant is always finite. |
| assumption-gate- | T01-T04, T08, T11 | Derived state is capped by the earliest finite VERIFIED support; future observations are stale. |
| agent-action-guard | T05-T07, T11 | Grant construction and validation require a finite half-open interval. |
| token-governance-protocol | T09-T11 | Reservation expiry is finite and capped by budget validity. |
| EASL | T02, T08, T11 | Existing exact-expiry semantics remain; observations after Snapshot.At are invalid input. |
| Aegis-EGE Kubernetes drain | T01-T07, T11 | Explicit evaluation time; finite assumption and authority windows required before commit. |

## Compatibility and old artifacts

Historical artifacts remain readable evidence. They are not silently upgraded to
new authorization guarantees.

New authorizing paths fail closed on security-invalid legacy shapes:
- AuthorityGrant without a finite `expires_at`;
- finite required-input lifetime projected to a longer/null child lifetime;
- malformed temporal fields;
- exact-expiry reuse;
- future-dated evidence/checks under a zero-skew profile.

This profile does not claim that every domain uses wall-clock expiry. Domains may
define state-bound or immutable evidence, but the absence rule must be explicit
and may not erase a finite required dependency.
