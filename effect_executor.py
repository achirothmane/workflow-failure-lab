"""Deferred effect boundary for CI Retry Gate.

The composite Action persists the Decision Evidence Record first, then invokes this
executor. The executor re-verifies every persisted contract, re-reads current GitHub
state, and only then dispatches a rerun.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ci_retry_gate import GitHubAPI, revalidate_rerun_subject_binding, redact
from decision_record import DecisionRecordError, read_decision_record
from effect_plan import EffectPlanError, read_effect_plan
from eba_integration_contract import (
    ASSUMPTION_KIND,
    AUTHORITY_KIND,
    DECISION_KIND,
    ContractViolation,
    build_execution_receipt,
    ensure_decision_allows_request,
    read_contract_artifact,
    write_contract_artifact,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def _required(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _load_decision_experience() -> dict:
    raw = str(os.environ.get("INPUT_DECISION_EXPERIENCE_JSON") or "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _emit_summary(*, outcome: str, reason: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n### Effect boundary\n\n")
        handle.write(f"- Outcome: `{outcome}`\n")
        handle.write(f"- Reason: {reason}\n")


def main() -> int:
    try:
        token = _required("INPUT_GITHUB_TOKEN")
        plan_path = _required("INPUT_EFFECT_PLAN_PATH")
        plan_sha = _required("INPUT_EFFECT_PLAN_SHA256")
        decision_record_path = _required("INPUT_DECISION_RECORD_PATH")
        decision_record_sha = _required("INPUT_DECISION_RECORD_SHA256")
        request_path = _required("INPUT_EBA_REQUEST_PATH")
        request_sha = _required("INPUT_EBA_REQUEST_SHA256")
        assumption_path = _required("INPUT_EBA_ASSUMPTION_PATH")
        assumption_sha = _required("INPUT_EBA_ASSUMPTION_SHA256")
        authority_path = _required("INPUT_EBA_AUTHORITY_PATH")
        authority_sha = _required("INPUT_EBA_AUTHORITY_SHA256")
        decision_path = _required("INPUT_EBA_DECISION_PATH")
        decision_sha = _required("INPUT_EBA_DECISION_SHA256")
        receipt_path = _required("INPUT_EBA_RECEIPT_PATH")

        plan = read_effect_plan(plan_path, expected_sha256=plan_sha)
        repo = str(plan["repository"])
        decision_record = read_decision_record(
            decision_record_path,
            expected_sha256=decision_record_sha,
        )
        if plan["decision_record_sha256"] != decision_record["record_sha256"]:
            raise RuntimeError("effect plan/Decision Evidence Record digest mismatch")

        action_request = read_contract_artifact(
            request_path,
            expected_sha256=request_sha,
            expected_kind="ActionRequest",
        )
        assumption_state = read_contract_artifact(
            assumption_path,
            expected_sha256=assumption_sha,
            expected_kind=ASSUMPTION_KIND,
        )
        authority_grant = read_contract_artifact(
            authority_path,
            expected_sha256=authority_sha,
            expected_kind=AUTHORITY_KIND,
        )
        contract_decision = read_contract_artifact(
            decision_path,
            expected_sha256=decision_sha,
            expected_kind=DECISION_KIND,
        )
    except (
        RuntimeError,
        EffectPlanError,
        DecisionRecordError,
        ContractViolation,
    ) as exc:
        print(f"::error::deferred effect boundary could not verify persisted state: {redact(str(exc))}")
        return 2

    mutation_admitted = bool(plan["mutation_admitted"])
    rerun_triggered = False
    receipt_outcome = "NOT_EXECUTED"
    effect_reason = "MUTATION_NOT_ADMITTED"
    admitted_at: str | None = None

    if mutation_admitted:
        if decision_record.get("decision") != "ALLOW":
            effect_reason = "DECISION_RECORD_NOT_ALLOW"
        else:
            api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
            evidence_decision = {
                "scope": dict(plan["scope"]),
            }
            expected_failed_jobs = list(plan["failed_jobs"])
            try:
                binding_valid, binding_reason = revalidate_rerun_subject_binding(
                    api,
                    repo,
                    int(plan["run_id"]),
                    evidence_decision,
                    expected_failed_jobs,
                )
            except RuntimeError as exc:
                binding_valid = False
                binding_reason = (
                    "RERUN_SCOPE_UNAVAILABLE: could not re-read current workflow state "
                    f"before deferred rerun: {redact(str(exc))}"
                )

            if not binding_valid:
                effect_reason = binding_reason
            else:
                admitted_at = _now_iso()
                try:
                    ensure_decision_allows_request(
                        contract_decision,
                        action_request,
                        now=admitted_at,
                        assumption_states=[assumption_state],
                        authority_grant=authority_grant,
                    )
                except ContractViolation as exc:
                    effect_reason = f"INTEGRATION_CONTRACT_BLOCK: {exc}"
                else:
                    try:
                        api.rerun_failed_jobs(repo, int(plan["run_id"]))
                    except RuntimeError as exc:
                        # A transport failure can occur after GitHub accepted the POST.
                        # Do not claim NOT_EXECUTED when the effect is epistemically unknown.
                        receipt_outcome = "UNKNOWN"
                        effect_reason = f"RERUN_DISPATCH_UNKNOWN: {redact(str(exc))}"
                    else:
                        rerun_triggered = True
                        receipt_outcome = "SUCCEEDED"
                        effect_reason = "RERUN_DISPATCH_ACCEPTED"

    receipt = build_execution_receipt(
        action_request=action_request,
        decision_artifact=contract_decision,
        assumption_states=[assumption_state],
        authority_grant=authority_grant,
        rerun_triggered=rerun_triggered,
        admitted_at=admitted_at,
        execution_reason=effect_reason,
        execution_outcome=receipt_outcome,
    )
    receipt_sha = write_contract_artifact(receipt_path, receipt)

    experience = _load_decision_experience()
    execution = experience.get("execution")
    if isinstance(execution, dict):
        execution["rerun_triggered"] = rerun_triggered
        execution["effect_outcome"] = receipt_outcome
        execution["effect_reason"] = effect_reason

    _write_output("rerun-triggered", "true" if rerun_triggered else "false")
    _write_output("effect-outcome", receipt_outcome)
    _write_output("effect-reason", effect_reason)
    _write_output("eba-receipt-path", str(Path(receipt_path)))
    _write_output("eba-receipt-sha256", receipt_sha)
    _write_output(
        "eba-receipt-json",
        json.dumps(receipt, separators=(",", ":"), sort_keys=True),
    )
    if experience:
        _write_output(
            "decision-experience-json",
            json.dumps(experience, separators=(",", ":"), sort_keys=True),
        )

    _emit_summary(outcome=receipt_outcome, reason=effect_reason)

    # UNKNOWN is not retried here. The caller receives the receipt and a successful
    # process exit so reconciliation can determine what GitHub actually did later.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
