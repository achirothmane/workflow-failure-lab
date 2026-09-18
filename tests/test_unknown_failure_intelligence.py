from __future__ import annotations

from benchmark_mode import render_benchmark_report, summarize_benchmark
from history_ci_waste import HistoricalFailure
from recovery_ground_truth import (
    RECOVERY_NOT_OBSERVED,
    RECOVERY_NOT_RECOVERED,
    RECOVERY_UNVERIFIED,
    RECOVERY_VALIDATED,
)
from unknown_failure_intelligence import (
    PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS,
    PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES,
    PROMOTION_BLOCKER_NO_STABLE_SIGNATURE,
    PROMOTION_BLOCKER_RECOVERY_RATE,
    PROMOTION_BLOCKER_SEMANTIC_EVIDENCE,
    PROMOTION_BLOCKER_SIDE_EFFECT,
    PROMOTION_BLOCKER_TRANSIENT_MECHANISM,
    PROMOTION_ELIGIBLE,
    STATUS_INSUFFICIENT_EVIDENCE,
    STATUS_INVESTIGATE_TRANSIENT,
    STATUS_NOT_TRANSIENT,
    STATUS_SIDE_EFFECT_GUARDED,
    extract_unknown_evidence,
    summarize_unknown_patterns,
    unknown_pattern_id,
    unknown_signature,
)


def _unknown(
    run_id: int,
    *,
    signature: str = "fatal: remote cache service unavailable for shard <n>",
    recovered: bool = True,
    observed: bool = True,
    side_effect: bool = False,
    recovery_status: str | None = None,
    unknown_cause: str = "",
) -> HistoricalFailure:
    if recovery_status is None:
        if not observed:
            recovery_status = RECOVERY_NOT_OBSERVED
        elif recovered:
            recovery_status = RECOVERY_VALIDATED
        else:
            recovery_status = RECOVERY_NOT_RECOVERED
    return HistoricalFailure(
        run_id=run_id,
        job_name="build",
        category="UNKNOWN",
        confidence="low",
        duration_minutes=1.5,
        fingerprint=f"FG-{run_id}",
        signature=signature,
        recovered_after_rerun=recovered,
        rerun_observed=observed,
        side_effect_risk=side_effect,
        attempt=1,
        recovery_status=recovery_status,
        unknown_cause=unknown_cause,
    )


def test_unknown_evidence_extracts_generic_errors_and_redacts_secrets():
    evidence = extract_unknown_evidence(
        "setup ok\n"
        "ERROR upload failed api_key=super-secret-value request 12345\n"
        "fatal: remote cache service unavailable for shard 88\n"
    )

    assert len(evidence) == 2
    assert "[redacted]" in evidence[0]
    assert "super-secret-value" not in evidence[0]
    assert "<n>" in evidence[0]
    assert "<n>" in evidence[1]


def test_unknown_signature_is_stable_under_dynamic_numbers():
    one = unknown_signature("fatal: remote cache service unavailable for shard 123")
    two = unknown_signature("fatal: remote cache service unavailable for shard 987")

    assert one == two
    assert unknown_pattern_id(one) == unknown_pattern_id(two)


def test_unknown_pattern_requires_three_real_reruns_and_eighty_percent_recovery():
    signature = "fatal: remote cache service unavailable for shard <n>"
    histories = {"acme/repo": ([_unknown(1, signature=signature)], 1)}
    reruns = {
        "acme/repo": (
            [
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
                _unknown(4, signature=signature, recovered=True),
            ],
            3,
        )
    }

    summary = summarize_unknown_patterns(histories, reruns)
    pattern = summary.patterns[0]

    assert pattern.occurrences == 4
    assert pattern.rerun_observations == 3
    assert pattern.recoveries == 3
    assert pattern.recovery_rate == 1.0
    assert pattern.status == STATUS_INVESTIGATE_TRANSIENT
    assert pattern.promotion_candidate is True


def test_unknown_pattern_does_not_promote_with_too_few_reruns():
    signature = "fatal: remote cache service unavailable"
    summary = summarize_unknown_patterns(
        {"acme/repo": ([_unknown(1, signature=signature)], 1)},
        {
            "acme/repo": (
                [
                    _unknown(2, signature=signature, recovered=True),
                    _unknown(3, signature=signature, recovered=True),
                ],
                2,
            )
        },
    )

    assert summary.patterns[0].status == STATUS_INSUFFICIENT_EVIDENCE


def test_unknown_pattern_side_effect_guard_overrides_high_recovery():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True, side_effect=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    summary = summarize_unknown_patterns({}, reruns)
    assert summary.patterns[0].status == STATUS_SIDE_EFFECT_GUARDED
    assert summary.promotion_candidates == ()


def test_unknown_pattern_with_low_recovery_is_not_transient():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=False),
                _unknown(3, signature=signature, recovered=False),
                _unknown(4, signature=signature, recovered=False),
            ],
            4,
        )
    }

    summary = summarize_unknown_patterns({}, reruns)
    assert summary.patterns[0].status == STATUS_NOT_TRANSIENT


def test_unknown_intelligence_can_aggregate_same_signature_across_repositories():
    signature = "fatal: remote cache service unavailable"
    histories = {
        "acme/one": ([_unknown(1, signature=signature)], 1),
        "acme/two": ([_unknown(2, signature=signature)], 1),
    }

    summary = summarize_unknown_patterns(histories, {})
    assert len(summary.patterns) == 1
    assert summary.patterns[0].occurrences == 2
    assert summary.patterns[0].repositories == 2
    assert summary.repeated_patterns == 1


def test_benchmark_report_surfaces_unknown_intelligence_without_promoting_runtime():
    signature = "fatal: remote cache service unavailable"
    summary = summarize_benchmark(
        {"acme/repo": ([_unknown(1, signature=signature)], 1)},
        rerun_histories={
            "acme/repo": (
                [
                    _unknown(2, signature=signature, recovered=True),
                    _unknown(3, signature=signature, recovered=True),
                    _unknown(4, signature=signature, recovered=True),
                ],
                3,
            )
        },
    )

    report = render_benchmark_report(summary)
    assert "Unknown Failure Intelligence" in report
    assert "UNKNOWN Promotion Blocker Attribution" in report
    assert "UNKNOWN Pattern Promotion Readiness" in report
    assert "ELIGIBLE_FOR_CLASSIFIER_RESEARCH" in report
    assert "does not modify the runtime classifier or authorize reruns" in report
    assert len(summary.unknown_intelligence.promotion_candidates) == 1


def test_unknown_evidence_ignores_benign_digest_mismatch_setting_and_shell_comment():
    evidence = extract_unknown_evidence(
        "2026-09-18T00:15:16.1305147Z digest-mismatch: error\n"
        "2026-09-18T00:15:16.1305200Z # beep on error\n"
    )
    assert evidence == ()


def test_unknown_evidence_keeps_real_digest_mismatch_error():
    evidence = extract_unknown_evidence(
        "2026-09-18T00:15:16.1305147Z Error: digest mismatch expected abc got def\n"
    )
    assert evidence == ("error: digest mismatch expected abc got def",)


def test_unknown_evidence_keeps_github_error_annotation():
    evidence = extract_unknown_evidence(
        "2026-09-18T00:15:16.1305147Z ##[error]The operation was canceled.\n"
    )
    assert evidence == ("##[error]the operation was canceled.",)


def test_unknown_evidence_does_not_match_error_inside_package_name():
    evidence = extract_unknown_evidence(
        "2026-09-18T00:15:16.1305147Z downloaded proc-macro-error-attr2 v2.0.0\n"
    )
    assert evidence == ()


def test_noise_only_unknown_signature_cannot_be_promoted():
    noisy_log = (
        "2026-09-18T00:15:16.1305147Z digest-mismatch: error\n"
        "2026-09-18T00:15:16.1305200Z # beep on error\n"
    )
    signature = unknown_signature(noisy_log)
    assert signature == "unknown without stable evidence"

    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
                _unknown(4, signature=signature, recovered=True),
            ],
            4,
        )
    }
    summary = summarize_unknown_patterns({}, reruns)
    assert summary.patterns[0].status == STATUS_INSUFFICIENT_EVIDENCE
    assert summary.promotion_candidates == ()


def test_unknown_unverified_success_does_not_promote_pattern():
    signature = "temporary resolver exploded"
    rerun = {
        "acme/repo": (
            [
                _unknown(
                    1,
                    signature=signature,
                    recovered=True,
                    recovery_status=RECOVERY_UNVERIFIED,
                ),
                _unknown(
                    2,
                    signature=signature,
                    recovered=True,
                    recovery_status=RECOVERY_UNVERIFIED,
                ),
                _unknown(
                    3,
                    signature=signature,
                    recovered=True,
                    recovery_status=RECOVERY_UNVERIFIED,
                ),
            ],
            3,
        )
    }

    summary = summarize_unknown_patterns({}, rerun)
    pattern = summary.patterns[0]

    assert pattern.rerun_observations == 0
    assert pattern.recoveries == 0
    assert pattern.unknown_outcomes == 3
    assert pattern.promotion_candidate is False


def test_unknown_cause_summary_aggregates_by_family_and_repository():
    histories = {
        "acme/one": (
            [
                _unknown(
                    1,
                    signature="error: permission denied",
                    unknown_cause="AUTH_PERMISSION",
                ),
                _unknown(
                    2,
                    signature="error: failed to push some refs",
                    unknown_cause="GIT_VCS",
                ),
            ],
            2,
        ),
        "acme/two": (
            [
                _unknown(
                    3,
                    signature="fatal: authentication failed",
                    unknown_cause="AUTH_PERMISSION",
                )
            ],
            1,
        ),
    }
    reruns = {
        "acme/one": (
            [
                _unknown(
                    4,
                    signature="error: permission denied",
                    recovered=False,
                    unknown_cause="AUTH_PERMISSION",
                )
            ],
            1,
        )
    }

    summary = summarize_unknown_patterns(histories, reruns)
    by_cause = {item.cause: item for item in summary.causes}

    assert sum(item.occurrences for item in summary.causes) == summary.unknown_failures
    assert by_cause["AUTH_PERMISSION"].occurrences == 3
    assert by_cause["AUTH_PERMISSION"].repositories == 2
    assert by_cause["AUTH_PERMISSION"].rerun_observations == 1
    assert by_cause["AUTH_PERMISSION"].failed_again == 1
    assert by_cause["GIT_VCS"].occurrences == 1


def test_benchmark_report_surfaces_unknown_cause_decomposition():
    summary = summarize_benchmark(
        {
            "acme/repo": (
                [
                    _unknown(
                        1,
                        signature="error: permission denied",
                        unknown_cause="AUTH_PERMISSION",
                    )
                ],
                1,
            )
        }
    )

    report = render_benchmark_report(summary)

    assert "UNKNOWN Cause Decomposition" in report
    assert "`AUTH_PERMISSION`" in report
    assert "diagnostic buckets only" in report


def test_promotion_blocker_attribution_reports_all_missing_requirements():
    signature = "fatal: remote cache service unavailable"
    summary = summarize_unknown_patterns(
        {"acme/repo": ([_unknown(1, signature=signature)], 1)},
        {
            "acme/repo": (
                [
                    _unknown(
                        2,
                        signature=signature,
                        observed=False,
                        recovered=False,
                    )
                ],
                1,
            )
        },
    )

    pattern = summary.patterns[0]
    assert pattern.promotion_candidate is False
    assert pattern.promotion_blocker == PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES
    assert pattern.promotion_blockers == (
        PROMOTION_BLOCKER_INSUFFICIENT_OCCURRENCES,
        PROMOTION_BLOCKER_INSUFFICIENT_GT_RERUNS,
    )
    assert pattern.occurrence_deficit == 1
    assert pattern.gt_rerun_deficit == 3
    assert pattern.promotion_distance == 2


def test_promotion_blocker_distinguishes_low_recovery_from_missing_samples():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=False),
                _unknown(3, signature=signature, recovered=False),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_blockers == (PROMOTION_BLOCKER_RECOVERY_RATE,)
    assert pattern.promotion_blocker == PROMOTION_BLOCKER_RECOVERY_RATE
    assert pattern.recovery_rate == 1 / 3
    assert pattern.recovery_rate_deficit > 0
    assert pattern in summarize_unknown_patterns({}, reruns).near_promotion_candidates


def test_promotion_blocker_reports_side_effect_contamination_even_with_good_recovery():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True, side_effect=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_blockers == (PROMOTION_BLOCKER_SIDE_EFFECT,)
    assert pattern.promotion_blocker == PROMOTION_BLOCKER_SIDE_EFFECT
    assert pattern.promotion_distance == 1


def test_promotion_blocker_marks_ready_pattern_as_eligible():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    summary = summarize_unknown_patterns({}, reruns)
    pattern = summary.patterns[0]

    assert pattern.promotion_candidate is True
    assert pattern.promotion_blocker == PROMOTION_ELIGIBLE
    assert pattern.promotion_blockers == ()
    assert pattern.promotion_distance == 0


def test_no_stable_signature_is_explicit_promotion_blocker():
    signature = "unknown without stable evidence"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_blocker == PROMOTION_BLOCKER_NO_STABLE_SIGNATURE
    assert PROMOTION_BLOCKER_NO_STABLE_SIGNATURE in pattern.promotion_blockers


def test_promotion_blocker_counts_and_near_candidates_are_exposed():
    ready_signature = "fatal: service unavailable"
    low_recovery_signature = "fatal: connection reset by peer"
    summary = summarize_unknown_patterns(
        {},
        {
            "acme/repo": (
                [
                    _unknown(1, signature=ready_signature, recovered=True),
                    _unknown(2, signature=ready_signature, recovered=True),
                    _unknown(3, signature=ready_signature, recovered=True),
                    _unknown(4, signature=low_recovery_signature, recovered=True),
                    _unknown(5, signature=low_recovery_signature, recovered=False),
                    _unknown(6, signature=low_recovery_signature, recovered=False),
                ],
                6,
            )
        },
    )

    counts = dict(summary.promotion_blocker_counts)
    assert counts[PROMOTION_ELIGIBLE] == 1
    assert counts[PROMOTION_BLOCKER_RECOVERY_RATE] == 1
    assert len(summary.near_promotion_candidates) == 1


def test_semantic_noise_blocks_promotion_even_with_perfect_ground_truth_recovery():
    signature = (
        "test alt_registry::cannot_publish_to_crates_io_with_registry_dependency ... ok | "
        "test cargo_alias_config::alias_cannot_shadow_builtin_command ... ok"
    )
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    summary = summarize_unknown_patterns({}, reruns)
    pattern = summary.patterns[0]

    assert pattern.recovery_rate == 1.0
    assert pattern.promotion_candidate is False
    assert pattern.promotion_blockers == (PROMOTION_BLOCKER_SEMANTIC_EVIDENCE,)
    assert pattern.semantic_accepted_segments == ()
    assert "SUCCESSFUL_TEST_LINE" in pattern.semantic_reasons


def test_generic_runner_wrapper_blocks_promotion_despite_perfect_recovery():
    signature = "##[error]process completed with exit code <n>."
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_candidate is False
    assert pattern.promotion_blocker == PROMOTION_BLOCKER_SEMANTIC_EVIDENCE
    assert "GENERIC_RUNNER_WRAPPER" in pattern.semantic_reasons


def test_specific_failure_signature_still_promotes_when_other_thresholds_pass():
    signature = "fatal: remote cache service unavailable"
    reruns = {
        "acme/repo": (
            [
                _unknown(1, signature=signature, recovered=True),
                _unknown(2, signature=signature, recovered=True),
                _unknown(3, signature=signature, recovered=True),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_candidate is True
    assert pattern.promotion_blockers == ()
    assert pattern.semantic_accepted_segments == (signature,)


def test_deterministic_command_config_cannot_promote_from_recovery_alone():
    signature = "could not find file: /workspace/uv.toml"
    reruns = {
        "acme/repo": (
            [
                _unknown(
                    1,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
                _unknown(
                    2,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
                _unknown(
                    3,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.recovery_rate == 1.0
    assert pattern.promotion_candidate is False
    assert pattern.promotion_blockers == (PROMOTION_BLOCKER_TRANSIENT_MECHANISM,)
    assert pattern.mechanism_status == "DETERMINISTIC_MECHANISM"
    assert pattern.mechanism_reasons == ("COMMAND_CONFIG",)


def test_specific_but_unproven_mechanism_cannot_promote_from_recovery_alone():
    signature = "fatal: remote cache checksum mismatch"
    reruns = {
        "acme/repo": (
            [
                _unknown(
                    1,
                    signature=signature,
                    recovered=True,
                    unknown_cause="AMBIGUOUS_OPERATIONAL",
                ),
                _unknown(
                    2,
                    signature=signature,
                    recovered=True,
                    unknown_cause="AMBIGUOUS_OPERATIONAL",
                ),
                _unknown(
                    3,
                    signature=signature,
                    recovered=True,
                    unknown_cause="AMBIGUOUS_OPERATIONAL",
                ),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_candidate is False
    assert pattern.promotion_blockers == (PROMOTION_BLOCKER_TRANSIENT_MECHANISM,)
    assert pattern.mechanism_status == "TRANSIENT_MECHANISM_UNPROVEN"
    assert pattern.mechanism_reasons == ("NO_TRANSIENT_MECHANISM_EVIDENCE",)


def test_explicit_transient_mechanism_can_override_deterministic_diagnostic_family():
    signature = "error: command failed after connection reset by peer"
    reruns = {
        "acme/repo": (
            [
                _unknown(
                    1,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
                _unknown(
                    2,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
                _unknown(
                    3,
                    signature=signature,
                    recovered=True,
                    unknown_cause="COMMAND_CONFIG",
                ),
            ],
            3,
        )
    }

    pattern = summarize_unknown_patterns({}, reruns).patterns[0]

    assert pattern.promotion_candidate is True
    assert pattern.promotion_blockers == ()
    assert pattern.mechanism_status == "TRANSIENT_MECHANISM_SUPPORTED"
    assert "CONNECTION_RESET" in pattern.mechanism_reasons
    assert pattern.mechanism_causes == ("COMMAND_CONFIG",)

