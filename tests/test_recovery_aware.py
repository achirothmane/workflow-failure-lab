import unittest

from ci_retry_gate import FAILURE_CONCLUSIONS, assess_failed_jobs, detect_cross_attempt_recovery, detect_cross_attempt_recurrence, detect_recovered_failures, historical_reliability_record, collect_historical_reliability


class RecoveryAwareEvidenceTests(unittest.TestCase):
    def test_explicit_successful_retry_recovers_failed_primary(self):
        failed = [{
            "id": 101262549936,
            "name": "dogfooding-lint / 🛠️ Dogfooding Lint",
            "conclusion": "failure",
        }]
        jobs = failed + [{
            "id": 101265017746,
            "name": "dogfooding_lint_retry / 🛠️ Dogfooding Lint (retry)",
            "conclusion": "success",
        }]

        recovered = detect_recovered_failures(failed, jobs)

        self.assertEqual(
            recovered,
            {101262549936: "dogfooding_lint_retry / 🛠️ Dogfooding Lint (retry)"},
        )

    def test_unrelated_success_does_not_count_as_recovery(self):
        failed = [{
            "id": 1,
            "name": "lint / Lint",
            "conclusion": "failure",
        }]
        jobs = failed + [{
            "id": 2,
            "name": "tests / Tests",
            "conclusion": "success",
        }]

        self.assertEqual(detect_recovered_failures(failed, jobs), {})

    def test_retry_with_different_display_identity_does_not_match(self):
        failed = [{
            "id": 1,
            "name": "lint / Lint",
            "conclusion": "failure",
        }]
        jobs = failed + [{
            "id": 2,
            "name": "tests_retry / Tests (retry)",
            "conclusion": "success",
        }]

        self.assertEqual(detect_recovered_failures(failed, jobs), {})

    def test_later_attempt_same_jobs_proves_cross_attempt_recovery(self):
        failed = [
            {"id": 10, "name": "E2E Tests (shard 4/4)", "conclusion": "failure"},
            {"id": 11, "name": "E2E Tests", "conclusion": "failure"},
        ]
        later = [
            {"id": 20, "name": "E2E Tests (shard 4/4)", "conclusion": "success"},
            {"id": 21, "name": "E2E Tests", "conclusion": "success"},
        ]

        self.assertEqual(
            detect_cross_attempt_recovery(failed, later),
            {10: "E2E Tests (shard 4/4)", 11: "E2E Tests"},
        )

    def test_partial_later_attempt_does_not_prove_full_recovery(self):
        failed = [
            {"id": 10, "name": "E2E Tests (shard 4/4)", "conclusion": "failure"},
            {"id": 11, "name": "E2E Tests", "conclusion": "failure"},
        ]
        later = [{"id": 20, "name": "E2E Tests (shard 4/4)", "conclusion": "success"}]

        self.assertEqual(
            detect_cross_attempt_recovery(failed, later),
            {10: "E2E Tests (shard 4/4)"},
        )

    def test_history_respects_cutoff_and_is_non_authorizing(self):
        current = [{"id": 30, "name": "E2E Tests", "conclusion": "failure"}]
        incidents = [
            {
                "observed_at": "2026-09-24T11:16:28Z",
                "failed_jobs": [{"id": 10, "name": "E2E Tests", "conclusion": "failure"}],
                "later_jobs": [{"id": 20, "name": "E2E Tests", "conclusion": "success"}],
            },
            {
                "observed_at": "2026-09-24T18:00:00Z",
                "failed_jobs": [{"id": 11, "name": "E2E Tests", "conclusion": "failure"}],
                "later_jobs": [{"id": 21, "name": "E2E Tests", "conclusion": "success"}],
            },
        ]

        record = historical_reliability_record(
            current, incidents, "2026-09-24T17:49:01Z"
        )

        self.assertEqual(record["status"], "SUPPORTING_EVIDENCE")
        self.assertEqual(record["verified_prior_recoveries"], 1)
        self.assertEqual(record["authorization"], "NOT_AUTHORIZING")
        self.assertEqual(
            record["latest_verified_recovery_at"], "2026-09-24T11:16:28Z"
        )

    def test_history_without_verified_recovery_is_insufficient(self):
        record = historical_reliability_record(
            [{"id": 30, "name": "E2E Tests", "conclusion": "failure"}],
            [],
            "2026-09-24T17:49:01Z",
        )
        self.assertEqual(record["status"], "INSUFFICIENT_HISTORY")
        self.assertEqual(record["verified_prior_recoveries"], 0)
        self.assertEqual(record["authorization"], "NOT_AUTHORIZING")

    def test_collector_uses_only_prior_rerun_runs(self):
        class FakeAPI:
            def get_workflow_runs(self, repo, workflow_id, per_page=100, page=1):
                if page > 1:
                    return []
                return [
                    {"id": 100, "workflow_id": workflow_id, "created_at": "2026-09-24T11:16:28Z", "run_attempt": 2},
                    {"id": 200, "workflow_id": workflow_id, "created_at": "2026-09-24T18:00:00Z", "run_attempt": 2},
                ]

            def get_jobs_attempt(self, repo, run_id, attempt):
                if run_id == 100 and attempt == 1:
                    return [{"id": 10, "name": "E2E Tests", "conclusion": "failure"}]
                if run_id == 100 and attempt == 2:
                    return [{"id": 20, "name": "E2E Tests", "conclusion": "success"}]
                raise AssertionError("future run must not be inspected")

        record = collect_historical_reliability(
            FakeAPI(),
            "Midtown-Technology-Group/bifrost",
            {
                "id": 300,
                "workflow_id": 250387439,
                "created_at": "2026-09-24T17:49:01Z",
            },
            [{"id": 30, "name": "E2E Tests", "conclusion": "failure"}],
        )

        self.assertEqual(record["verified_prior_recoveries"], 1)
        self.assertEqual(record["candidate_runs"], 1)
        self.assertEqual(record["candidate_runs_inspected"], 1)
        self.assertEqual(record["pages_examined"], 1)
        self.assertEqual(record["authorization"], "NOT_AUTHORIZING")


    def test_next_attempt_recurrence_is_not_recovery(self):
        failed = [{"id": 1, "name": "test-environment-validation", "conclusion": "failure"}]
        next_attempt = [{"id": 2, "name": "test-environment-validation", "conclusion": "failure"}]
        self.assertEqual(detect_cross_attempt_recovery(failed, next_attempt), {})
        self.assertEqual(detect_cross_attempt_recurrence(failed, next_attempt), {1: "test-environment-validation"})


    def test_minipdf_later_success_does_not_create_prior_history(self):
        current = [{"id": 1, "name": "test (10, ubuntu-22.04)", "conclusion": "failure"}]
        self.assertEqual(
            detect_cross_attempt_recovery(
                current,
                [{"id": 2, "name": "test (10, ubuntu-22.04)", "conclusion": "success"}],
            ),
            {1: "test (10, ubuntu-22.04)"},
        )
        history = historical_reliability_record(current, [], "2026-09-19T07:06:47Z")
        self.assertEqual(history["verified_prior_incidents"], 0)
        self.assertEqual(history["authorization"], "NOT_AUTHORIZING")

    def test_tortoise_partial_recovery_is_not_full_workflow_recovery(self):
        failed = [
            {"id": 1, "name": "changes", "conclusion": "failure"},
            {"id": 2, "name": "python-ci-gate", "conclusion": "failure"},
        ]
        later = [
            {"id": 3, "name": "changes", "conclusion": "success"},
            {"id": 4, "name": "python-ci-gate", "conclusion": "failure"},
        ]
        recovered = detect_cross_attempt_recovery(failed, later)
        self.assertEqual(recovered, {1: "changes"})
        self.assertNotEqual(len(recovered), len(failed))

    def test_pglite_separate_run_is_not_cross_attempt_evidence(self):
        failed = [{"id": 1, "name": "Build and Test packages/pglite (24.x)", "conclusion": "failure"}]
        # A separate workflow run is deliberately not supplied to the cross-attempt matcher.
        self.assertEqual(detect_cross_attempt_recovery(failed, []), {})

    def test_kitsune_mixed_recovery_and_recurrence_remain_distinct(self):
        failed = [
            {"id": 1, "name": "Add comment of changelog preview / changelog-preview-comment", "conclusion": "failure"},
            {"id": 2, "name": "test-windows (windows-latest)", "conclusion": "failure"},
            {"id": 3, "name": "ci_pass", "conclusion": "failure"},
        ]
        later = [
            {"id": 11, "name": "Add comment of changelog preview / changelog-preview-comment", "conclusion": "failure"},
            {"id": 12, "name": "test-windows (windows-latest)", "conclusion": "success"},
            {"id": 13, "name": "ci_pass", "conclusion": "success"},
        ]
        self.assertEqual(
            detect_cross_attempt_recovery(failed, later),
            {2: "test-windows (windows-latest)", 3: "ci_pass"},
        )
        self.assertEqual(
            detect_cross_attempt_recurrence(failed, later),
            {1: "Add comment of changelog preview / changelog-preview-comment"},
        )


    def test_cancelled_jobs_are_not_failure_candidates(self):
        jobs = [
            {"id": 1, "name": "failed", "conclusion": "failure"},
            {"id": 2, "name": "timed", "conclusion": "timed_out"},
            {"id": 3, "name": "cancelled", "conclusion": "cancelled"},
        ]
        candidates = [job["name"] for job in jobs if job["conclusion"] in FAILURE_CONCLUSIONS]
        self.assertEqual(candidates, ["failed", "timed"])
        self.assertNotIn("cancelled", FAILURE_CONCLUSIONS)

    def test_history_rate_limit_is_explicit_and_non_authorizing(self):
        class RateLimitedAPI:
            def get_workflow_runs(self, repo, workflow_id, per_page=100, page=1):
                raise RuntimeError("GitHub API rate limit exceeded")

        record = collect_historical_reliability(
            RateLimitedAPI(),
            "example/repo",
            {"id": 9, "workflow_id": 7, "created_at": "2026-09-24T18:00:00Z"},
            [{"id": 1, "name": "tests", "conclusion": "failure"}],
        )
        self.assertEqual(record["status"], "EVIDENCE_RATE_LIMITED")
        self.assertTrue(record["evidence_budget_exhausted"])
        self.assertEqual(record["authorization"], "NOT_AUTHORIZING")

    def test_history_candidate_budget_exhaustion_is_explicit(self):
        class BudgetAPI:
            def get_workflow_runs(self, repo, workflow_id, per_page=100, page=1):
                return [
                    {"id": 100 + i, "workflow_id": workflow_id, "created_at": "2026-09-20T00:00:00Z", "run_attempt": 2}
                    for i in range(3)
                ]

            def get_jobs_attempt(self, repo, run_id, attempt):
                return []

        record = collect_historical_reliability(
            BudgetAPI(),
            "example/repo",
            {"id": 999, "workflow_id": 7, "created_at": "2026-09-24T18:00:00Z"},
            [{"id": 1, "name": "tests", "conclusion": "failure"}],
            max_pages=1,
            max_candidate_runs=2,
        )
        self.assertTrue(record["evidence_budget_exhausted"])
        self.assertEqual(record["authorization"], "NOT_AUTHORIZING")


    def test_public_log_403_fails_closed_as_evidence_unavailable(self):
        class ForbiddenLogsAPI:
            def get_job_logs(self, repo, job_id):
                raise RuntimeError(
                    'GitHub API GET /repos/example/repo/actions/jobs/42/logs failed with HTTP 403: '
                    '{"message":"Must have admin rights to Repository."}'
                )

        assessments = assess_failed_jobs(
            ForbiddenLogsAPI(),
            "example/repo",
            [{
                "id": 42,
                "name": "public-test",
                "conclusion": "failure",
                "steps": [{"name": "Run tests", "conclusion": "failure"}],
            }],
        )
        self.assertEqual(len(assessments), 1)
        item = assessments[0]
        self.assertEqual(item.category, "EVIDENCE_UNAVAILABLE")
        self.assertEqual(item.confidence, "none")
        self.assertEqual(item.provenance_status, "UNAVAILABLE")
        self.assertEqual(item.failure_step_status, "FAILURE_STEP_CONFIRMED")
        self.assertIn("HTTP 403", item.evidence[0])


if __name__ == "__main__":
    unittest.main()
