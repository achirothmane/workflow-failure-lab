from decision_identity import collect_decision_identities, github_actor_identity


def test_github_actor_identity_preserves_raw_principal_and_type() -> None:
    assert github_actor_identity({"login": "alice", "type": "User"}) == {
        "raw": "alice",
        "identity_type": "human",
    }
    assert github_actor_identity({"login": "dependabot[bot]", "type": "Bot"}) == {
        "raw": "dependabot[bot]",
        "identity_type": "bot",
    }
    assert github_actor_identity({"login": "my-app[bot]", "type": "App"}) == {
        "raw": "my-app[bot]",
        "identity_type": "github_app",
    }


def test_collect_identities_adds_token_principal_only_for_effect_request() -> None:
    run = {
        "actor": {"login": "alice", "type": "User"},
        "triggering_actor": {"login": "release-bot", "type": "Bot"},
    }

    report_only = collect_decision_identities(run, rerun_will_be_requested=False)
    assert "rerun_initiator" not in report_only

    mutating = collect_decision_identities(run, rerun_will_be_requested=True)
    assert mutating["workflow_actor"]["raw"] == "alice"
    assert mutating["workflow_triggering_actor"]["identity_type"] == "bot"
    assert mutating["rerun_initiator"] == {
        "raw": "github-token",
        "identity_type": "token",
    }
