# Implementation Plan — Workflow Failure Lab v0.1

Status: Draft for B1. Governs the first vertical slice only.
Vocabulary and retry rules are fixed by [ADR-0001](adr/0001-scope-and-vocabulary.md); this plan may not redefine them.

## 1. First Vertical Slice

One execution goes in, one incident report comes out. Nothing else.

### Input file

A single JSON file, path given as a CLI argument:

```
python -m workflow_failure_lab report <path/to/execution.json>
```

The file contains **one execution and its steps**:

- `execution`: `id`, `workflow_name`, `started_at`, `finished_at` (nullable), `status` (raw string as recorded by the source system).
- `steps`: ordered list; each step has `id`, `name`, `started_at`, `finished_at` (nullable), `status` (raw string), `attempt` (int ≥ 1), optional `error` (`message`, plus optional `kind`).

The exact JSON Schema (Draft 2020-12) is authored in B2 and lives with the parsing module; this plan fixes only the shape above.

### Processing path

```
CLI arg → parsing → domain model → analysis → reporting → stdout
```

1. **parsing** — read the file, validate against the JSON Schema, map to frozen domain objects. Invalid input stops here with a clear error naming the failing field; nothing partial reaches analysis.
2. **analysis** — walk the steps, classify the execution as `SUCCEEDED`, `FAILED_CONFIRMED`, or `INDETERMINATE` per ADR-0001, and collect the evidence (which steps/fields) supporting the classification. Missing or ambiguous evidence classifies as `INDETERMINATE` — never optimistically.
3. **retry_policy** — given the classification, state whether retry is permitted and whether reconciliation is required, per the two binding rules in ADR-0001.
4. **reporting** — render one Markdown incident report to stdout: execution summary, classification, evidence list, retry/reconciliation guidance.

### Output shape

Markdown printed to stdout, deterministic for a given input (no timestamps of "now", no randomness), with these sections in order:

1. `# Incident Report: <workflow_name> / <execution id>`
2. `## Classification` — one of the three vocabulary terms, verbatim.
3. `## Evidence` — bullet list, each bullet citing the step/field that supports the classification.
4. `## Retry Guidance` — permitted / forbidden, and whether reconciliation is required, quoting the applicable ADR-0001 rule.
5. `## Steps` — table of steps with status, attempt, and error message if any.

Exit code: 0 when a report is produced (regardless of classification), non-zero on invalid input or internal error.

## 2. Module Boundaries

All modules live under one package, `workflow_failure_lab`:

| Module | Responsibility | Explicitly not its job |
|---|---|---|
| `domain` | Frozen dataclasses for Execution/Step/Error, the three-term classification enum, evidence value objects | I/O, JSON, formatting, policy decisions |
| `parsing` | File reading, JSON Schema validation, mapping raw JSON → domain objects | Interpreting what a status *means* |
| `analysis` | Classify one execution from domain objects, produce evidence | Reading files, deciding on retries, formatting |
| `retry_policy` | Apply ADR-0001's two binding rules to a classification | Classifying, formatting |
| `reporting` | Render classification + evidence + retry guidance as Markdown | Any analysis or policy logic |

The CLI entry point (`__main__`) only wires these together in the order of the processing path.

## 3. Dependency Direction

```
parsing ──▶ domain ◀── analysis ◀── reporting
                 ◀── retry_policy ◀──┘
```

- **Rule: `domain` imports from no other module in the package.** It is the innermost layer.
- `parsing`, `analysis`, `retry_policy` import only `domain`.
- `reporting` imports `domain`, `analysis` (result types), and `retry_policy` (decision types).
- No module imports `parsing` except the CLI entry point. No cycles; enforced by a test in B-later, stated here as a rule now.

## 4. Non-Goals (v0.1)

- No database, web interface, AI model, agents, or cloud deployment (per problem statement).
- No Docker, Kafka, LangGraph, microservices, async runtime, or plugin system.
- No multi-execution batch analysis; exactly one execution per run.
- No executing or retrying workflows — the tool *advises* on retry, it never performs one.
- No reconciliation implementation — the tool states that reconciliation is required; performing it is out of scope.
- No config files, no persistence, no network calls.
- No speculative abstractions: no Protocol/ABC/Registry/Factory without a current second user.

## 5. Proposed Dependencies

| Dependency | Justification (one line) | No-dependency alternative |
|---|---|---|
| `jsonschema` (Draft 2020-12), runtime | Declarative, spec-compliant validation of the input file with precise error paths, instead of hand-written checks that drift | Hand-rolled validation functions in `parsing`: more code, weaker error messages, but zero runtime deps |
| `pytest`, tests only | Standard test runner already allow-listed in project permissions; fixtures/parametrize keep evidence-based tests small | `unittest` from the stdlib: works, but more boilerplate per case |

No other dependency is proposed. Everything else in the slice is stdlib (`argparse`, `dataclasses`, `json`, `enum`).
