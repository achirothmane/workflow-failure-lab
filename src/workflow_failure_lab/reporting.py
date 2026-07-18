"""Render classification, evidence, and retry guidance as Markdown.

No analysis or policy logic lives here; the report is deterministic for a
given input (no wall-clock timestamps, no randomness).
"""

from __future__ import annotations

from workflow_failure_lab.analysis import AnalysisResult
from workflow_failure_lab.domain import Execution
from workflow_failure_lab.retry_policy import RetryDecision


def render_report(
    execution: Execution, result: AnalysisResult, decision: RetryDecision
) -> str:
    lines: list[str] = []
    lines.append(f"# Incident Report: {execution.workflow_name} / {execution.id}")
    lines.append("")

    lines.append("## Classification")
    lines.append("")
    lines.append(result.classification.value)
    lines.append("")

    lines.append("## Evidence")
    lines.append("")
    for item in result.evidence:
        lines.append(f"- `{item.source}` — {item.detail}")
    lines.append("")

    lines.append("## Retry Guidance")
    lines.append("")
    lines.append(f"- Retry: {'permitted' if decision.retry_permitted else 'forbidden'}")
    lines.append(
        "- Reconciliation: "
        f"{'required' if decision.reconciliation_required else 'not required'}"
    )
    lines.append(f"- Applicable rule (ADR-0001): {decision.rule}")
    lines.append("")

    lines.append("## Steps")
    lines.append("")
    lines.append("| # | Step | Status | Attempt | Error |")
    lines.append("|---|------|--------|---------|-------|")
    for index, step in enumerate(execution.steps, start=1):
        error_message = step.error.message if step.error is not None else ""
        lines.append(
            f"| {index} | {_cell(step.name)} | {_cell(step.status)} "
            f"| {step.attempt} | {_cell(error_message)} |"
        )
    lines.append("")

    return "\n".join(lines)


def _cell(text: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")
