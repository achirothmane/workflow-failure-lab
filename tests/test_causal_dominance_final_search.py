from causal_dominance_final_search import (
    FINAL_SEARCH_SHARDS,
    validate_final_search_corpus,
)


def test_final_search_has_two_disjoint_50_repo_shards():
    assert set(FINAL_SEARCH_SHARDS) == {1, 2}
    assert len(FINAL_SEARCH_SHARDS[1]) == 50
    assert len(FINAL_SEARCH_SHARDS[2]) == 50

    all_repositories = FINAL_SEARCH_SHARDS[1] + FINAL_SEARCH_SHARDS[2]
    assert len(all_repositories) == 100
    assert len(set(all_repositories)) == 100


def test_final_search_does_not_reuse_prior_targeted_or_holdout_repositories():
    ok, reason = validate_final_search_corpus()

    assert ok is True
    assert "100 unique repositories" in reason
    assert "no prior search/holdout overlap" in reason
