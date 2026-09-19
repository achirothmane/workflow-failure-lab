import json

import pytest

from flaky_ownership import (
    CodeownersRule,
    OwnershipRule,
    codeowners_matches,
    load_ownership_map,
    parse_codeowners,
    resolve_codeowners,
    resolve_ownership,
)
from flaky_test_intelligence import (
    CaseObservation,
    FlakyTestSummary,
    QUARANTINE_CANDIDATE,
)


def summary(test_id: str) -> FlakyTestSummary:
    return FlakyTestSummary(
        test_id=test_id,
        observations=4,
        failures=2,
        passes=2,
        same_sha_flips=2,
        validated_recoveries=2,
        persistent_failure_shas=0,
        failed_seconds=20.0,
        recovery_seconds=18.0,
        estimated_waste_seconds=38.0,
        recommendation=QUARANTINE_CANDIDATE,
        reason="recovered twice",
    )


def obs(test_id: str, source_file: str) -> CaseObservation:
    return CaseObservation(
        test_id=test_id,
        sha="abc",
        run_id=1,
        attempt=1,
        status="fail",
        duration_seconds=1.0,
        source_file=source_file,
    )


def test_load_ownership_map_requires_version_and_owners():
    rules = load_ownership_map(
        json.dumps(
            {
                "version": 1,
                "rules": [
                    {
                        "test_pattern": "payments::*",
                        "owners": ["@payments-team"],
                        "route": "payments-ci",
                    }
                ],
            }
        )
    )

    assert rules == (
        OwnershipRule(
            test_pattern="payments::*",
            owners=("@payments-team",),
            route="payments-ci",
        ),
    )

    with pytest.raises(ValueError):
        load_ownership_map('{"version":2,"rules":[]}')


def test_codeowners_basic_matching_respects_path_depth():
    assert codeowners_matches("*.py", "tests/unit/test_cart.py")
    assert codeowners_matches("/tests/**", "tests/unit/test_cart.py")
    assert codeowners_matches("tests/*", "tests/test_cart.py")
    assert not codeowners_matches("tests/*", "tests/unit/test_cart.py")


def test_codeowners_last_matching_rule_wins():
    rules = parse_codeowners(
        """
        *.py @python
        /tests/payments/** @payments
        /tests/payments/special.py @special
        """
    )

    owners, pattern = resolve_codeowners("tests/payments/special.py", rules)

    assert owners == ("@special",)
    assert pattern == "/tests/payments/special.py"


def test_resolve_ownership_prefers_codeowners_when_unique_file_exists():
    test_id = "payments.test_checkout::test_card"
    resolutions = resolve_ownership(
        (summary(test_id),),
        (obs(test_id, "tests/payments/test_checkout.py"),),
        codeowners_rules=(
            CodeownersRule("/tests/payments/**", ("@payments-team",)),
        ),
        mapping_rules=(
            OwnershipRule("payments.*", ("@fallback",), "fallback"),
        ),
    )

    resolved = resolutions[test_id]
    assert resolved.owners == ("@payments-team",)
    assert resolved.source == "CODEOWNERS"
    assert resolved.source_file == "tests/payments/test_checkout.py"


def test_resolve_ownership_falls_back_to_test_id_map_without_source_file():
    test_id = "payments.test_checkout::test_card"
    resolutions = resolve_ownership(
        (summary(test_id),),
        (),
        mapping_rules=(
            OwnershipRule("payments.*", ("@payments-team",), "payments-ci"),
        ),
    )

    resolved = resolutions[test_id]
    assert resolved.owners == ("@payments-team",)
    assert resolved.source == "OWNERSHIP_MAP"
    assert resolved.route == "payments-ci"


def test_ambiguous_source_files_do_not_guess_codeowner_and_can_use_map():
    test_id = "pkg::test"
    resolutions = resolve_ownership(
        (summary(test_id),),
        (
            obs(test_id, "tests/a.py"),
            obs(test_id, "tests/b.py"),
        ),
        codeowners_rules=(
            CodeownersRule("/tests/**", ("@tests",)),
        ),
        mapping_rules=(
            OwnershipRule("pkg::*", ("@explicit",), "explicit-route"),
        ),
    )

    resolved = resolutions[test_id]
    assert resolved.owners == ("@explicit",)
    assert resolved.source == "OWNERSHIP_MAP"
    assert resolved.source_file == ""


def test_unmatched_test_remains_explicitly_unresolved():
    test_id = "unknown::test"
    resolutions = resolve_ownership((summary(test_id),), ())

    resolved = resolutions[test_id]
    assert not resolved.resolved
    assert resolved.source == "UNRESOLVED"
