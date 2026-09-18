from independent_replication_gate import (
    MIN_INDEPENDENT_RUNS,
    REPLICATION_CONFIRMED,
    REPLICATION_INSUFFICIENT,
    assess_independent_replication,
)


def test_single_run_is_not_independent_replication():
    result = assess_independent_replication({101}, {"acme/repo"})

    assert result.status == REPLICATION_INSUFFICIENT
    assert result.independent_runs == 1
    assert result.independent_repositories == 1
    assert result.run_deficit == MIN_INDEPENDENT_RUNS - 1
    assert result.cross_repository is False


def test_two_distinct_runs_confirm_replication_inside_one_repository():
    result = assess_independent_replication({101, 202}, {"acme/repo"})

    assert result.status == REPLICATION_CONFIRMED
    assert result.independent_runs == 2
    assert result.run_deficit == 0
    assert result.cross_repository is False


def test_duplicate_samples_from_same_run_do_not_inflate_replication():
    result = assess_independent_replication((101, 101, 101), ("acme/repo",))

    assert result.status == REPLICATION_INSUFFICIENT
    assert result.run_ids == (101,)
    assert result.independent_runs == 1


def test_cross_repository_replication_is_reported_as_stronger_evidence():
    result = assess_independent_replication(
        {101, 202, 303},
        {"acme/repo", "other/project"},
    )

    assert result.status == REPLICATION_CONFIRMED
    assert result.independent_repositories == 2
    assert result.cross_repository is True
