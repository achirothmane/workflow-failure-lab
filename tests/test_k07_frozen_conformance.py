from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


CONFORMANCE_DIR = Path(__file__).parent / "conformance" / "governed_action"
ORACLE_PATH = CONFORMANCE_DIR / "normative-cases.json"
EXECUTION_PATH = CONFORMANCE_DIR / "k07-executable-cases.json"

SOURCE_AEGIS_COMMIT = "2b08f173d7e0dc7390b7ba9fec57ab10e28c48ba"
SOURCE_ORACLE_BLOB = "37e2e0a0867fa78df37f9d4243a1c4107d62094b"
SOURCE_EXECUTION_BLOB = "89b971ab136d7b2c889c586429a803fec9587c0d"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload).hexdigest()


ORACLE = _load(ORACLE_PATH)
EXECUTION = _load(EXECUTION_PATH)
ORACLE_BY_ID = {case["id"]: case for case in ORACLE["cases"]}


def _is_shared_case(case: dict) -> bool:
    applicability = set(case["applicability"])
    return "generic" in applicability or "ci" in applicability


SHARED_ORACLE_CASES = [case for case in ORACLE["cases"] if _is_shared_case(case)]
SHARED_IDS = {case["id"] for case in SHARED_ORACLE_CASES}
SHARED_EXECUTION_CASES = [
    case for case in EXECUTION["cases"] if case["case_id"] in SHARED_IDS
]


def _evaluate(case: dict) -> dict:
    inp = case["input"]
    result = {
        "valid_trace": False,
        "disposition": "",
        "authorized_effects": 0,
        "unauthorized_effects": 0,
        "useful_behavior": False,
        "observations": [],
        "action_ref": case["action_ref"],
        "effect_id": case["effect_id"],
        "attempt_id": case["attempt_id"],
        "observation_ref": case["observation_ref"],
        "fault_schedule": case["fault_schedule"],
    }

    def reject(disposition: str, *observations: str) -> dict:
        result["valid_trace"] = False
        result["disposition"] = disposition
        result["observations"] = list(observations)
        result["authorized_effects"] = 0
        result["unauthorized_effects"] = 0
        result["useful_behavior"] = False
        return result

    def allow(disposition: str, *observations: str) -> dict:
        result["valid_trace"] = True
        result["disposition"] = disposition
        result["observations"] = list(observations)
        result["unauthorized_effects"] = 0
        result["useful_behavior"] = True
        if inp["emit_effect"]:
            result["authorized_effects"] = 1
        return result

    if not inp["profile_trusted"]:
        return reject("REJECT_BEFORE_EFFECT", "admission.profile=UNTRUSTED")
    if not inp["profile_adequate"]:
        return reject("DEFER_PROFILE_INCOMPLETE", "admission.profile=INADEQUATE_FOR_CLAIM")
    if not inp["revision_exact"] or not inp["current_witnesses"]:
        return reject("REJECT_BEFORE_EFFECT", "admission.basis=STALE_OR_WRONG_REVISION")
    if not inp["relevant_state_bound"]:
        return reject("DEFER_MISSING_RELEVANT_STATE", "decision_basis.relevant_state=MISSING")
    if not inp["relevant_state_current"]:
        return reject("REJECT_BEFORE_EFFECT", "decision_basis.relevant_state=STALE")
    if inp["required_independence"] and not inp["independence_satisfied"]:
        return reject(
            "DEFER_INSUFFICIENT_INDEPENDENCE",
            "evidence.independence=UNKNOWN_OR_UNSATISFIED",
        )
    if not inp["enforcement_boundary_declared"] or not inp["complete_mediation"]:
        return reject(
            "DEFER_ENFORCEMENT_ASSUMPTIONS_MISSING",
            "enforcement.boundary=UNPROVEN",
        )
    if inp["effect_can_survive_process"] and not inp["custody_before_dispatch"]:
        return reject("REJECT_TRACE", "custody.before_dispatch=MISSING")
    if inp["hard_precondition_required"] and not inp["destination_cas"]:
        return reject(
            "REJECT_UNGUARDED_MUTATION",
            "destination.precondition=NOT_ATOMIC",
        )
    if (
        inp["possible_effect_exists"]
        and inp["substitution_requested"]
        and not inp["safe_substitution_proven"]
    ):
        return reject(
            "REJECT_SECOND_EFFECT",
            "effect.previous=POSSIBLE",
            "substitution=UNPROVEN",
        )
    if inp["observation_gap"]:
        if inp["terminal_unknown_authorized"] and inp["residual_custody"]:
            return allow(
                "RETIRE_AS_UNKNOWN",
                "closure.knowledge=UNKNOWN",
                "closure.disposition=RETIRED_UNKNOWN",
                "closure.custody=RETAINED",
            )
        return reject(
            "REJECT_DISPOSITION",
            "closure.knowledge=UNKNOWN",
            "closure.custody=INSUFFICIENT",
        )
    if inp["takeover_requested"]:
        if (
            inp["stale_worker_can_act"]
            and not inp["destination_fencing_effective"]
            and not inp["takeover_blocked"]
        ):
            return reject(
                "REJECT_TAKEOVER_EFFECT",
                "takeover.exclusivity=UNPROVEN",
                "effect.previous=ACCOUNTED",
            )
        return allow(
            "ALLOW_SAFE_RECOVERY_OR_BLOCK",
            "takeover.exclusivity=ENFORCED_OR_BLOCKED",
            "effect.lineage=PRESERVED",
        )
    if inp["verified_outcome_claim"] and not inp["postcondition_exact"]:
        return reject(
            "REJECT_FALSE_VERIFIED",
            "outcome.postcondition=UNSATISFIED_OR_UNRELATED",
        )

    seed_mode = inp["seed_mode"]
    if seed_mode == "ci_validated_rerun":
        return allow(
            "DISCHARGE_RECOVERY_OBLIGATION",
            "ci.dispatch=ACCEPTED",
            "ci.recovery=VALIDATED",
        )
    if seed_mode == "kube_bounded_drain":
        return allow(
            "DISCHARGE_CLOSURE_MATCH",
            "kubernetes.postflight=MATCH",
            "kubernetes.custody=CHECKPOINTED",
        )
    if seed_mode == "eep_conditional_update":
        return allow(
            "DISCHARGE_INTENDED_STATE_OBLIGATION",
            "eep.request=ACCEPTED",
            "eep.postcondition=VERIFIED",
            "eep.observation=OBSERVED_STABLE",
        )
    if seed_mode == "eep_already_satisfied":
        return allow(
            "DISCHARGE_INTENDED_STATE_OBLIGATION",
            "eep.request=NOT_DISPATCHED",
            "eep.postcondition=ALREADY_SATISFIED",
        )

    if inp["verified_outcome_claim"] and inp["postcondition_exact"]:
        return allow(
            "DISCHARGE_INTENDED_STATE_OBLIGATION",
            "eep.postcondition=VERIFIED",
        )
    if inp["possible_effect_exists"] and not inp["substitution_requested"]:
        return allow(
            "RETAIN_POSSIBLE_EFFECT",
            "effect.previous=POSSIBLE",
            "effect.custody=RETAINED",
            "effect.replay=BLOCKED",
        )

    return allow("ALLOW_BOUND_EFFECT", f"{inp['domain']}.effect=PERMITTED")


def test_k07_snapshots_pin_exact_aegis_frozen_sources() -> None:
    assert SOURCE_AEGIS_COMMIT == "2b08f173d7e0dc7390b7ba9fec57ab10e28c48ba"
    assert _git_blob_sha(ORACLE_PATH) == SOURCE_ORACLE_BLOB
    assert _git_blob_sha(EXECUTION_PATH) == SOURCE_EXECUTION_BLOB
    assert ORACLE["schema_version"] == "governed-action.normative-cases/v1"
    assert ORACLE["contract_status"] == "FROZEN"
    assert EXECUTION["schema_version"] == "governed-action.k07-execution/v1"
    assert EXECUTION["frozen_oracle_blob"] == SOURCE_ORACLE_BLOB


def test_k07_python_scope_exactly_covers_shared_generic_and_ci_cases() -> None:
    execution_ids = {case["case_id"] for case in SHARED_EXECUTION_CASES}
    assert execution_ids == SHARED_IDS

    # WFL is not the semantic owner for domain-only Kubernetes/EEP cases.
    assert "SEED-KUBE-A1-bounded-drain-completes" not in execution_ids
    assert "SEED-EEP-A1-conditional-update-verified" not in execution_ids
    assert "SEED-EEP-A2-already-satisfied-noop" not in execution_ids
    assert "CE7-R1-unrelated-change-as-success" not in execution_ids
    assert "CE7-A1-exact-postcondition-verified" not in execution_ids


@pytest.mark.parametrize(
    "case",
    SHARED_EXECUTION_CASES,
    ids=[case["case_id"] for case in SHARED_EXECUTION_CASES],
)
def test_k07_python_matches_frozen_shared_oracle(case: dict) -> None:
    expected = ORACLE_BY_ID[case["case_id"]]
    got = _evaluate(case)

    assert got["valid_trace"] is expected["valid_trace"]
    assert got["disposition"] == expected["expected"]["disposition"]
    assert got["unauthorized_effects"] == 0
    assert got["action_ref"]
    assert got["observations"]

    if not expected["valid_trace"]:
        assert got["authorized_effects"] == 0
        return

    assert got["useful_behavior"] is True

    if expected["expected"]["disposition"] == "ALLOW_BOUND_EFFECT":
        assert got["authorized_effects"] == 1

    if got["authorized_effects"] > 0:
        assert got["effect_id"]
        assert got["attempt_id"]

    if case["input"]["possible_effect_exists"]:
        assert got["effect_id"]


def test_k07_ci_seed_remains_domain_typed_in_python() -> None:
    case = next(
        case
        for case in SHARED_EXECUTION_CASES
        if case["case_id"] == "SEED-CI-A1-validated-rerun"
    )
    got = _evaluate(case)

    assert got["valid_trace"] is True
    assert got["disposition"] == "DISCHARGE_RECOVERY_OBLIGATION"
    assert "ci.dispatch=ACCEPTED" in got["observations"]
    assert "ci.recovery=VALIDATED" in got["observations"]
    assert got["authorized_effects"] == 1
