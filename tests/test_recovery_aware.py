import unittest

from ci_retry_gate import detect_cross_attempt_recovery, detect_cross_attempt_recurrence, detect_recovered_failures, historical_reliability_record, collect_historical_reliability


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


if __name__ == "__main__":
    unittest.main()
