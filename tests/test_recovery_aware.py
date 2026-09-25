import unittest

from ci_retry_gate import detect_cross_attempt_recovery, detect_recovered_failures


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


if __name__ == "__main__":
    unittest.main()
