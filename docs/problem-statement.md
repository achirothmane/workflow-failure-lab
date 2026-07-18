# Problem Statement

Workflow Failure Lab is a local tool for analyzing failed workflow executions.

The first user is a developer or automation engineer investigating an execution failure.

The input is a JSON file containing an execution and its steps.

The output is a Markdown incident report printed in the terminal.

SUCCEEDED means the execution completed with enough evidence of success.

FAILED_CONFIRMED means the execution failed and the failure is confirmed.

INDETERMINATE means the available data cannot prove success or confirmed failure.

Blind retry is forbidden when the result is INDETERMINATE.

Reconciliation means checking the external system before attempting the action again.

Version 0.1 will parse, validate, analyze, classify, and report one execution.

Version 0.1 will not include a database, web interface, AI model, agents, or cloud deployment.

The project starts as a local CLI so its behavior remains small, testable, and understandable.

An analysis succeeds only when its conclusion is supported by the input evidence.

Missing or ambiguous evidence must result in INDETERMINATE, not an optimistic conclusion.

Git history, tests, and repository files are the source of truth.
