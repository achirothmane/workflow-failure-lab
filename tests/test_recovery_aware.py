import unittest

from ci_retry_gate import detect_recovered_failures


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


if __name__ == "__main__":
    unittest.main()
