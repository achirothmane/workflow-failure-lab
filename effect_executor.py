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
from execution_lease import (
    ExecutionLeaseError,
    lease_digest,
    load_registry,
    read_execution_lease,
    verify_effect_ownership,
)
from linearizable_lease import LinearizableLeaseError, verify_fencing_token
from external_monotonic_root import (
    DEFAULT_PREDICATE_TYPE,
    ExternalMonotonicRootError,
    verify_external_monotonic_root,
)
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
        safe_value = " ".join(str(value).splitlines())
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={safe_value}\n")


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

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))

    lease = None
    lease_block_reason: str | None = None
    lease_path = str(os.environ.get("INPUT_EXECUTION_LEASE_PATH") or "").strip()
    lease_registry_dir = str(
        os.environ.get("INPUT_EXECUTION_LEASE_REGISTRY_DIR") or ""
    ).strip()
    executor_id = str(os.environ.get("INPUT_EXECUTOR_ID") or "").strip()
    lease_guard_requested = bool(lease_path or lease_registry_dir or executor_id)

    if lease_guard_requested:
        if not lease_path or not lease_registry_dir or not executor_id:
            lease_block_reason = (
                "EXECUTION_LEASE_BLOCK: lease path, registry directory, and executor ID "
                "must be supplied together"
            )
        else:
            try:
                lease = read_execution_lease(lease_path)
                verify_effect_ownership(
                    candidate_lease=lease,
                    registry_leases=load_registry(lease_registry_dir),
                    expected_owner_id=executor_id,
                    decision_record_sha256=decision_record_sha,
                    effect_plan_sha256=plan_sha,
                    repository=repo,
                    run_id=int(plan["run_id"]),
                    now=_now_iso(),
                )
            except ExecutionLeaseError as exc:
                lease_block_reason = f"EXECUTION_LEASE_BLOCK: {redact(str(exc))}"

    coordination_ref = str(
        os.environ.get("INPUT_LINEARIZABLE_COORDINATION_REF") or ""
    ).strip()
    fencing_token_sha = str(
        os.environ.get("INPUT_LINEARIZABLE_FENCING_TOKEN_SHA") or ""
    ).strip()
    witness_ref = str(
        os.environ.get("INPUT_LINEARIZABLE_WITNESS_REF") or ""
    ).strip()
    linearizable_guard_requested = bool(
        coordination_ref or fencing_token_sha or witness_ref
    )
    linearizable_block_reason: str | None = None

    if linearizable_guard_requested:
        if not coordination_ref or not fencing_token_sha:
            linearizable_block_reason = (
                "LINEARIZABLE_FENCE_BLOCK: coordination ref and fencing token "
                "must be supplied together"
            )
        else:
            try:
                verify_fencing_token(
                    api,
                    repo,
                    coordination_ref=coordination_ref,
                    fencing_token_sha=fencing_token_sha,
                    witness_ref=witness_ref or None,
                    expected_decision_record_sha256=decision_record_sha,
                    expected_effect_plan_sha256=plan_sha,
                )
            except (LinearizableLeaseError, RuntimeError) as exc:
                linearizable_block_reason = (
                    f"LINEARIZABLE_FENCE_BLOCK: {redact(str(exc))}"
                )

    external_root_record_path = str(
        os.environ.get("INPUT_EXTERNAL_MONOTONIC_ROOT_RECORD_PATH") or ""
    ).strip()
    external_root_anchor_path = str(
        os.environ.get("INPUT_EXTERNAL_MONOTONIC_ROOT_ANCHOR_PATH") or ""
    ).strip()
    external_root_bundle_path = str(
        os.environ.get("INPUT_EXTERNAL_MONOTONIC_ROOT_BUNDLE_PATH") or ""
    ).strip()
    external_root_signer_workflow = str(
        os.environ.get("INPUT_EXTERNAL_MONOTONIC_ROOT_SIGNER_WORKFLOW") or ""
    ).strip()
    external_root_predicate_type = str(
        os.environ.get("INPUT_EXTERNAL_MONOTONIC_ROOT_PREDICATE_TYPE")
        or DEFAULT_PREDICATE_TYPE
    ).strip()
    external_root_guard_requested = bool(
        external_root_record_path
        or external_root_anchor_path
        or external_root_bundle_path
        or external_root_signer_workflow
    )
    external_root_block_reason: str | None = None
    external_root_record = None

    if external_root_guard_requested:
        if (
            not external_root_record_path
            or not external_root_anchor_path
            or not external_root_bundle_path
            or not external_root_signer_workflow
            or not fencing_token_sha
        ):
            external_root_block_reason = (
                "EXTERNAL_MONOTONIC_ROOT_BLOCK: root record, stable anchor, "
                "attestation bundle, signer workflow, and presented fencing token "
                "must be supplied together"
            )
        elif linearizable_block_reason is None:
            try:
                external_root_record = verify_external_monotonic_root(
                    api,
                    repo,
                    root_record_path=external_root_record_path,
                    anchor_path=external_root_anchor_path,
                    attestation_bundle_path=external_root_bundle_path,
                    signer_workflow=external_root_signer_workflow,
                    predicate_type=external_root_predicate_type,
                    presented_token_sha=fencing_token_sha,
                    run_id=int(plan["run_id"]),
                    decision_record_sha256=decision_record_sha,
                    effect_plan_sha256=plan_sha,
                )
            except (ExternalMonotonicRootError, RuntimeError) as exc:
                detail = " ".join(redact(str(exc)).split())
                external_root_block_reason = (
                    f"EXTERNAL_MONOTONIC_ROOT_BLOCK: {detail}"
                )

    if mutation_admitted:
        if linearizable_block_reason is not None:
            effect_reason = linearizable_block_reason
        elif external_root_block_reason is not None:
            effect_reason = external_root_block_reason
        elif lease_block_reason is not None:
            effect_reason = lease_block_reason
        elif decision_record.get("decision") != "ALLOW":
            effect_reason = "DECISION_RECORD_NOT_ALLOW"
        else:
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
    _write_output(
        "linearizable-fence-enforced",
        "true" if linearizable_guard_requested else "false",
    )
    _write_output("linearizable-coordination-ref", coordination_ref)
    _write_output("linearizable-fencing-token-sha", fencing_token_sha)
    _write_output("linearizable-witness-ref", witness_ref)
    _write_output(
        "external-monotonic-root-enforced",
        "true" if external_root_guard_requested else "false",
    )
    _write_output("external-monotonic-root-anchor-path", external_root_anchor_path)
    _write_output(
        "external-monotonic-root-token-sha",
        str(external_root_record.get("fencing_token_sha") or "")
        if isinstance(external_root_record, dict)
        else "",
    )
    _write_output(
        "external-monotonic-root-epoch",
        str(external_root_record.get("epoch") or "")
        if isinstance(external_root_record, dict)
        else "",
    )
    _write_output(
        "external-monotonic-root-state",
        str(external_root_record.get("lifecycle_state") or "")
        if isinstance(external_root_record, dict)
        else "",
    )
    _write_output("execution-lease-enforced", "true" if lease_guard_requested else "false")
    _write_output(
        "execution-lease-owner",
        str(lease.get("owner_id") or "") if isinstance(lease, dict) else "",
    )
    _write_output(
        "execution-lease-epoch",
        str(lease.get("epoch") or "") if isinstance(lease, dict) else "",
    )
    _write_output(
        "execution-lease-sha256",
        lease_digest(lease) if isinstance(lease, dict) else "",
    )
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
