from __future__ import annotations

from benchmark_mode import render_benchmark_report, summarize_benchmark
from history_ci_waste import HistoricalFailure
from unknown_failure_intelligence import (
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
) -> HistoricalFailure:
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
    assert "INVESTIGATE_TRANSIENT_PATTERN" in report
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
