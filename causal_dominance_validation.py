from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from causal_dominance_evidence import (
    INDEPENDENT_CAUSAL_DOMINANCE_POSITIVE_RUNS,
    VALIDATED_SERVER5XX_EVIDENCE,
)
from ci_retry_gate import assess_failure_step_provenance, classify_log, detect_side_effect_risk
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED, assess_mechanism_causality
from pinned_research_corpus import SWC_DPRINT_HTTP_504
from recovery_ground_truth import RECOVERY_VALIDATED, assess_recovery_ground_truth
from root_cause_precedence import (
    DOMINANCE_CANDIDATE,
    DOMINANCE_NOT_APPLICABLE,
    DOMINANCE_ORDERING_UNPROVEN,
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
    assess_causal_dominance,
)
from transient_mechanism_gate import REASON_SERVER_5XX


MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION = 3


@dataclass(frozen=True)
class ControlResult:
    name: str
    expected: str
    observed: str
    passed: bool
    real_case: bool = False


@dataclass(frozen=True)
class ValidationSummary:
    controls: tuple[ControlResult, ...]
    evidence_ledger_ok: bool
    evidence_ledger_count: int
    evidence_wave_counts: tuple[tuple[int, int], ...]
    independent_real_positive_controls: int
    holdout_present: bool
    holdout_clean: bool
    holdout_reason: str
    production_promotion_ready: bool

    @property
    def controls_passed(self) -> bool:
        return all(item.passed for item in self.controls)


def _job(step_name: str = "Run tests") -> dict:
    return {
        "name": "control",
        "conclusion": "failure",
        "steps": [
            {
                "name": step_name,
                "conclusion": "failure",
                "started_at": "2026-09-18T10:00:00Z",
                "completed_at": "2026-09-18T10:00:10Z",
            }
        ],
    }


def _evaluate_real_swc_positive() -> ControlResult:
    case = SWC_DPRINT_HTTP_504
    classification = classify_log(case.failure_log)
    mechanism = assess_mechanism_causality(case.failed_job, case.failure_log)
    failure_step = assess_failure_step_provenance(case.failed_job)
    recovery = assess_recovery_ground_truth(
        original_job=case.failed_job,
        failure_step_status=failure_step.status,
        failure_step=failure_step.step_name,
        rerun_observed=True,
        recovered=True,
        rerun_job=case.rerun_job,
    )
    side_effect, _ = detect_side_effect_risk(case.failed_job)
    dominance = assess_causal_dominance(case.failed_job, case.failure_log)

    passed = (
        classification.category == "CODE_REGRESSION"
        and mechanism.status == MECHANISM_CAUSAL_CONFIRMED
        and REASON_SERVER_5XX in mechanism.reasons
        and recovery.status == RECOVERY_VALIDATED
        and side_effect is False
        and dominance.status == DOMINANCE_CANDIDATE
        and dominance.proposed_category == "DEPENDENCY_NETWORK"
    )
    observed = (
        f"{classification.category}/{dominance.status}/"
        f"{recovery.status}/side_effect={side_effect}"
    )
    return ControlResult(
        name=case.case_id,
        expected="CODE_REGRESSION -> DOMINANCE_CANDIDATE -> VALIDATED_RECOVERY",
        observed=observed,
        passed=passed,
        real_case=True,
    )


def _evaluate_negative_controls() -> tuple[ControlResult, ...]:
    controls: list[ControlResult] = []

    before_log = (
        "2026-09-18T10:00:02.0000000Z Error: assertion failed: left == right\n"
        "2026-09-18T10:00:03.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "`-p app --test unit`\n"
    )
    before = assess_causal_dominance(_job(), before_log)
    controls.append(
        ControlResult(
            "deterministic-assertion-before-5xx",
            DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
            before.status,
            before.status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
        )
    )

    after_log = (
        "2026-09-18T10:00:02.0000000Z Error: HTTP 504 Gateway Timeout\n"
        "2026-09-18T10:00:03.0000000Z Error: TypeError: undefined is not a function\n"
        "2026-09-18T10:00:04.0000000Z error: test failed, to rerun pass "
        "`-p app --test unit`\n"
    )
    after = assess_causal_dominance(_job(), after_log)
    controls.append(
        ControlResult(
            "deterministic-typeerror-after-5xx",
            DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
            after.status,
            after.status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
        )
    )

    ordering_log = (
        "2026-09-18T10:00:01.0000000Z Error: tests failed\n"
        "2026-09-18T10:00:02.0000000Z Error: test failure\n"
        "2026-09-18T10:00:03.0000000Z Error: HTTP 504 Gateway Timeout\n"
    )
    ordering = assess_causal_dominance(_job(), ordering_log)
    controls.append(
        ControlResult(
            "wrapper-before-5xx",
            DOMINANCE_ORDERING_UNPROVEN,
            ordering.status,
            ordering.status == DOMINANCE_ORDERING_UNPROVEN,
        )
    )

    unknown_log = "2026-09-18T10:00:02.0000000Z Error: HTTP 500: Server Error\n"
    unknown = assess_causal_dominance(_job("Download"), unknown_log)
    controls.append(
        ControlResult(
            "unknown-5xx-does-not-use-dominance",
            DOMINANCE_NOT_APPLICABLE,
            unknown.status,
            unknown.status == DOMINANCE_NOT_APPLICABLE,
        )
    )
    return tuple(controls)


def _evidence_ledger_integrity() -> tuple[bool, int, tuple[tuple[int, int], ...]]:
    cases = VALIDATED_SERVER5XX_EVIDENCE
    wave_counts = tuple(sorted(Counter(item.wave for item in cases).items()))
    unique_keys = {
        (item.repository, item.run_id, item.job_name)
        for item in cases
    }
    ok = (
        len(cases) == 11
        and len(unique_keys) == 11
        and wave_counts == ((1, 4), (2, 1), (3, 6))
        and all(item.recovery_status == "VALIDATED_RECOVERY" for item in cases)
    )
    return ok, len(cases), wave_counts


def _evaluate_holdout(payload: dict[str, object] | None) -> tuple[bool, str]:
    if payload is None:
        return False, "not supplied"

    requested = int(payload.get("repositories_requested", 0))
    analyzed = int(payload.get("repositories_analyzed", 0))
    skipped = int(payload.get("repositories_skipped", 0))
    unresolved = int(payload.get("unresolved", 0))
    failed_again = int(payload.get("candidate_failed_again", 0))
    unknown = int(payload.get("candidate_unknown_outcomes", 0))

    reasons: list[str] = []
    if requested <= 0 or analyzed != requested:
        reasons.append(f"coverage={analyzed}/{requested}")
    if skipped:
        reasons.append(f"skipped={skipped}")
    if unresolved:
        reasons.append(f"unresolved={unresolved}")
    if failed_again:
        reasons.append(f"failed_again={failed_again}")
    if unknown:
        reasons.append(f"unknown_candidate_outcomes={unknown}")

    if reasons:
        return False, ", ".join(reasons)
    return True, (
        f"clean {analyzed}/{requested}; failed_again=0; "
        "unknown_candidate_outcomes=0; unresolved=0"
    )


def evaluate_validation(
    holdout_payload: dict[str, object] | None = None,
) -> ValidationSummary:
    controls = (_evaluate_real_swc_positive(),) + _evaluate_negative_controls()
    ledger_ok, ledger_count, wave_counts = _evidence_ledger_integrity()
    real_positive_controls = len(
        {
            (repository, run_id)
            for repository, run_id, _label
            in INDEPENDENT_CAUSAL_DOMINANCE_POSITIVE_RUNS
        }
    )
    holdout_clean, holdout_reason = _evaluate_holdout(holdout_payload)
    holdout_present = holdout_payload is not None

    production_ready = (
        all(item.passed for item in controls)
        and ledger_ok
        and holdout_present
        and holdout_clean
        and real_positive_controls
        >= MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION
    )

    return ValidationSummary(
        controls=controls,
        evidence_ledger_ok=ledger_ok,
        evidence_ledger_count=ledger_count,
        evidence_wave_counts=wave_counts,
        independent_real_positive_controls=real_positive_controls,
        holdout_present=holdout_present,
        holdout_clean=holdout_clean,
        holdout_reason=holdout_reason,
        production_promotion_ready=production_ready,
    )


def render_validation(summary: ValidationSummary) -> str:
    lines = [
        "## Causal Dominance Positive-Control Validation",
        "",
        "> This gate validates sensitivity and deterministic blocking without changing "
        "the production classifier or retry authority.",
        "",
        f"- Control suite passed: **{'yes' if summary.controls_passed else 'NO'}**",
        f"- Historical SERVER_5XX ledger: **{summary.evidence_ledger_count}** validated recoveries",
        f"- Ledger integrity: **{'yes' if summary.evidence_ledger_ok else 'NO'}**",
        f"- Independent real dominance-positive controls: **{summary.independent_real_positive_controls}**",
        f"- Production evidence minimum: **{MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION}**",
        f"- Holdout supplied: **{'yes' if summary.holdout_present else 'no'}**",
        f"- Holdout clean: **{'yes' if summary.holdout_clean else 'no'}**",
        f"- Holdout detail: {summary.holdout_reason}",
        f"- Production promotion ready: **{'YES' if summary.production_promotion_ready else 'NO'}**",
        "",
        "### Controls",
        "",
        "| Control | Expected | Observed | Result |",
        "|---|---|---|---|",
    ]
    for item in summary.controls:
        lines.append(
            f"| {item.name} | `{item.expected}` | `{item.observed}` | "
            f"{'PASS' if item.passed else 'FAIL'} |"
        )

    lines.extend(
        [
            "",
            "### Evidence accounting",
            "",
            f"- Wave counts: `{dict(summary.evidence_wave_counts)}`",
            "- The 11 validated recoveries establish SERVER_5XX mechanism-family evidence.",
            "- Pinned real causal-dominance positives: "
            + ", ".join(
                f"{repository}#{run_id}"
                for repository, run_id, _label
                in INDEPENDENT_CAUSAL_DOMINANCE_POSITIVE_RUNS
            )
            + ".",
            "",
        ]
    )
    if (
        summary.controls_passed
        and summary.evidence_ledger_ok
        and summary.holdout_present
        and summary.holdout_clean
        and not summary.production_promotion_ready
    ):
        deficit = (
            MIN_INDEPENDENT_REAL_POSITIVE_CONTROLS_FOR_PRODUCTION
            - summary.independent_real_positive_controls
        )
        lines.append(
            f"> Validation mechanics pass, but production promotion remains blocked: "
            f"need **{deficit}** more independent real causal-dominance positive "
            "control run(s)."
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout-json", type=Path)
    parser.add_argument("--require-clean-holdout", action="store_true")
    args = parser.parse_args()

    holdout = None
    if args.holdout_json:
        holdout = json.loads(args.holdout_json.read_text(encoding="utf-8"))

    summary = evaluate_validation(holdout)
    report = render_validation(summary)
    print(report)

    import os
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n" + report)

    if not summary.controls_passed or not summary.evidence_ledger_ok:
        return 1
    if args.require_clean_holdout and not summary.holdout_clean:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
