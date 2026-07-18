# Workflow Failure Lab

A local CLI that analyzes one failed workflow execution and prints a Markdown
incident report to stdout. The input is a JSON file containing an execution
and its steps; the output is deterministic for a given input.

## Certainty vocabulary

The report classifies the execution with exactly one of three terms, fixed by
[ADR-0001](docs/adr/0001-scope-and-vocabulary.md):

| Term | Meaning |
|---|---|
| `SUCCEEDED` | The execution completed with enough evidence of success. |
| `FAILED_CONFIRMED` | The execution failed and the failure is confirmed. |
| `INDETERMINATE` | The available data cannot prove success or confirmed failure. |

Two binding rules follow: retry is permitted if and only if the previous
attempt is `FAILED_CONFIRMED`, and `INDETERMINATE` requires reconciliation —
blind retry is forbidden.

## Install

Requires Python 3.12+.

```
pip install -e ".[test]"
```

or `make install`.

## Usage

```
python -m workflow_failure_lab report <path/to/execution.json>
```

For example:

```
python -m workflow_failure_lab report examples/payment-timeout.json
```

(also available as `make demo`). The report contains the execution summary,
classification, supporting evidence, retry/reconciliation guidance, and a
step table.

The `examples/` directory holds one input file per outcome, including a
malformed file that demonstrates input validation.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Report produced. The classification never affects the exit code. |
| 1 | Internal error (a bug): uncaught exception with a traceback. |
| 2 | Usage error: missing or unknown arguments. |
| 3 | Invalid input: unreadable file, invalid JSON, or schema violation. A concise message is printed to stderr. |

## Tests

```
pytest
```

or `make test`. CI runs the same suite on Python 3.12 (see
`.github/workflows/ci.yml`).
