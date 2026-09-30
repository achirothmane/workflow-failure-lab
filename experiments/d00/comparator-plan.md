# D00 — Native Comparator and Operator Baseline Preregistration

Status: **PREREGISTERED / PRE-INTERVENTION**
Owner: Workflow Failure Lab / Aegis experiment maintainers and the participating operator
Protocol version: `d00-comparator/v1`

D00 defines the measurement protocol that must exist before D01 changes operator behavior. It does not claim that governance saves time, improves outcomes, or is commercially valuable.

## 1. Eligible task semantics

### CI rerun task (D01)

Eligible task:

> For one exact owner-controlled GitHub repository/workflow/run/SHA/attempt/account, decide whether one failed execution is eligible for a bounded native rerun, perform at most the permitted rerun operation, and observe the resulting new attempt/outcome.

The task excludes:

- changing causal eligibility to obtain a rerun;
- rerunning another repository/account/workflow/run;
- shell/endpoint injection through analyzer output;
- production credentials held by remote analysis;
- ambiguous or missing mandatory identity/basis fields;
- retrospective deletion of difficult or UNKNOWN cases.

### Kubernetes node mutation task (D02 measurement compatibility)

D00's measurement dictionary may also record the existing bounded node-mutation experiment, but this preregistration does not execute D02 and does not grant new Kubernetes authority.

### Held-out D03

The same measurement dictionary may be extended to the independently selected D03 cohort after selection. D00 intentionally does not name, reveal, or predefine D03 cases.

## 2. Common safety and outcome standard

Both comparator arms must use the same:

- task semantics;
- account/repository/run/SHA/attempt identity where applicable;
- permitted operation and authority scope;
- eligibility/profile requirements;
- success/blocked/unknown outcome definitions;
- closure/accountability standard;
- case inclusion rule.

A comparator arm is invalid if it is deliberately weaker or granted broader authority than the governed arm.

## 3. Comparator arms

### Arm N — native composition

For D01, the native arm is the owner-controlled GitHub-native handling recipe in `native-baseline-ci.md`.

The operator performs the same identity/eligibility checks and invokes only the bounded native rerun operation using existing owner-controlled GitHub authority. No remote analyzer receives write authority.

### Arm G — governed composition

The governed arm is not implemented by D00. D01 will add:

`read-only analysis -> schema-validated proposal -> owner-controlled local verification -> same bounded native rerun -> observed result`

D00 records only the measurement fields and parity conditions that D01 must satisfy.

## 4. Observation method

Each eligible occurrence receives one immutable `case_id` and one or more observation records.

The operator records:

- task and identity bindings;
- arm;
- source kind;
- timestamps;
- active operator labor;
- elapsed waiting;
- provider latency as a subset of waiting;
- touches;
- installation, maintenance, exception and recovery active labor;
- outcome and closure disposition;
- inclusion/exclusion reason;
- authority/safety/task semantic references;
- redaction/secret-scan status.

Raw credentials, tokens, authorization headers, secret values and unrestricted provider logs are never measurement fields.

## 5. Time and touch accounting

`elapsed_seconds` is wall-clock time from observation start to end.

`active_seconds` is human attention/work time.

`waiting_seconds` is elapsed time in which the operator is not actively working.

`provider_latency_seconds` is the provider-dependent subset of waiting time and must not be added again when calculating total elapsed time.

The active subcategories:

- `installation_active_seconds`
- `maintenance_active_seconds`
- `exception_active_seconds`
- `recovery_active_seconds`

are parts of active labor. Their sum must not exceed `active_seconds`.

Touches are discrete operator interactions required to progress or close the task. Automated background events do not count as touches.

## 6. Baseline and intervention ordering

The first observed eligible recurrence for the CI task must be captured under the approved native arm before the corresponding governed intervention is used for a value comparison.

The synthetic dry-run fixture is not baseline evidence.

For later repeated comparable recurrences:

- record `sequence_position`;
- use a stable `crossover_group`;
- where both arms are safe and recurrence is independent, alternate N/G order across pairs;
- where alternating order would be unsafe or would alter the task, retain the native-first order and record `order_constraint`.

No causal savings claim is permitted from unmatched tasks or from order-confounded observations without explicit limitation.

## 7. Observation period

There is no arbitrary elapsed-day threshold.

Collection is tied to actual eligible task recurrence:

- begin before the corresponding intervention;
- retain every eligible attempted case during the experiment window;
- continue through D01/D02 attempts used by D04/D05;
- do not stop early because favorable results appeared.

If recurrence is too low for a fair comparison, D05 reports insufficient operator-value evidence rather than fabricating a percentage.

## 8. Historical versus observed data

Historical logs may inform planning only when recorded as `source_kind = historical_estimate`.

They are not mixed with:

- `synthetic_dry_run`;
- `observed_native`;
- `observed_governed`.

Only actual observed trials may support later operator-work conclusions.

## 9. Retention and redaction

Measurement records retain identifiers needed for reproducibility and joins, but exclude secrets.

Allowed examples:

- repository slug;
- workflow/run/attempt IDs;
- commit SHA;
- bounded account/resource identifier;
- timestamps;
- typed outcome/status;
- reason codes.

Forbidden examples:

- access tokens;
- private keys;
- Authorization header values;
- cookies/session secrets;
- raw environment dumps;
- unrelated provider payload content.

A record that fails the secret scan is rejected from committed evidence until redacted and revalidated.

## 10. Inclusion and denominator rule

All eligible attempted cases remain in the denominator, including:

- blocked cases;
- failures;
- UNKNOWN/ambiguous closure;
- recovery cases;
- cases requiring exception handling.

Exclusion requires a typed reason established by the preregistered eligibility rules. Difficult cases cannot be dropped because they make an arm look worse.

## 11. Adversarial accounting protections

D00 explicitly rejects:

1. omitting installation or maintenance labor;
2. moving operator work to another person/team and counting it as zero;
3. dropping UNKNOWN or failed cases;
4. deliberately weakening the native baseline;
5. selectively excluding difficult eligible cases;
6. counting provider latency as both waiting and labor;
7. counting the same setup/exception activity twice;
8. using unmatched task semantics or different safety standards;
9. granting broader authority to one arm;
10. inventing a universal percentage-savings target before observation.

## 12. Completion criteria

D00 is ready to unblock D01 when:

- the native and governed-arm parity rules are frozen in this preregistration;
- the measurement dictionary/schema are machine-checkable;
- the native CI recipe is owner-reviewable and uses no new third-party write authority;
- the representative dry-run passes timestamp/identity joins;
- active labor is separated from elapsed waiting/provider latency;
- the fixture contains no detectable secret material;
- no ungrounded savings percentage is encoded;
- the first real baseline observation will be collected before the governed intervention.

D00 does **not** itself produce a savings conclusion.

## 13. Failure / containment

If a fair native baseline or reliable operator observation cannot be obtained:

- do not issue a savings claim;
- keep technical conformance and safety evidence;
- preserve failed/incomplete cases;
- return to approved native handling;
- defer optional value-based extraction.
