# D00 Measurement Dictionary

Protocol: `d00-comparator/v1`

Each record is one observed or synthetic measurement interval for one eligible case.

| Field | Meaning |
|---|---|
| `record_id` | Unique record identifier. |
| `case_id` | Stable task occurrence identifier used to join all arm/phase records. |
| `protocol_version` | Must equal `d00-comparator/v1`. |
| `domain` | `ci`, `kubernetes`, or future held-out domain label. |
| `arm` | `native` or `governed`. |
| `source_kind` | `synthetic_dry_run`, `historical_estimate`, `observed_native`, or `observed_governed`. |
| `task_semantics_ref` | Immutable reference to the task definition. |
| `safety_standard_ref` | Immutable reference to the common safety standard. |
| `authority_scope_ref` | Bounded authority used for the task. |
| `account_ref` | Bounded account/resource identity; never a credential. |
| `repository` | Repository slug when applicable. |
| `workflow_ref` | Workflow identifier when applicable. |
| `run_id` | Provider run identifier when applicable. |
| `head_sha` | Exact code revision when applicable. |
| `run_attempt` | Exact provider attempt when applicable. |
| `started_at` / `ended_at` | RFC3339 timestamps. |
| `elapsed_seconds` | Wall-clock duration. |
| `active_seconds` | Human active labor. |
| `waiting_seconds` | Non-active elapsed waiting. |
| `provider_latency_seconds` | Provider-dependent subset of waiting. |
| `installation_active_seconds` | Setup labor, subset of active labor. |
| `maintenance_active_seconds` | Maintenance labor, subset of active labor. |
| `exception_active_seconds` | Exception-handling labor, subset of active labor. |
| `recovery_active_seconds` | Recovery labor, subset of active labor. |
| `touches` | Discrete operator interactions. |
| `outcome` | `completed`, `blocked`, `failed`, or `unknown`. |
| `closure_disposition` | Typed closure/disposition code; UNKNOWN remains explicit. |
| `included` | Whether record remains in the experiment denominator. |
| `exclusion_reason` | Required only when preregistered eligibility excludes it. |
| `sequence_position` | Order within comparable recurrence/crossover group. |
| `crossover_group` | Stable grouping for matched comparable recurrences. |
| `order_constraint` | Why alternation was not safe/possible, if applicable. |
| `secret_scan` | Must be `pass` before committed evidence is used. |
| `redaction_version` | Redaction policy version. |
| `notes_code` | Typed short code only; no raw logs/secrets. |

Accounting invariants:

- `ended_at >= started_at`.
- `elapsed_seconds >= active_seconds + waiting_seconds`.
- `provider_latency_seconds <= waiting_seconds`.
- active subcategory sum <= `active_seconds`.
- rejected/UNKNOWN cases are not excluded merely for being unfavorable.
- historical/synthetic records never count as observed intervention evidence.
