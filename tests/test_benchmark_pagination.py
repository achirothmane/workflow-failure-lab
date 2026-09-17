from benchmark_mode import _list_completed_runs


class _PagingDuplicateAPI:
    def request(self, method: str, path: str, payload=None, accept=None):
        assert method == "GET"
        if "page=1" in path:
            # Full first page with an intra-page duplicate. Three unique runs remain.
            return {
                "workflow_runs": [
                    {"id": 4, "run_attempt": 1},
                    {"id": 3, "run_attempt": 1},
                    {"id": 2, "run_attempt": 2},
                    {"id": 2, "run_attempt": 2},
                ]
            }
        if "page=2" in path:
            # Simulate offset pagination shifting while new runs arrive: run 2 repeats.
            return {"workflow_runs": [{"id": 2, "run_attempt": 2}]}
        if "page=3" in path:
            return {"workflow_runs": [{"id": 1, "run_attempt": 1}]}
        return {"workflow_runs": []}


def test_list_completed_runs_deduplicates_run_ids_across_moving_pages():
    runs = _list_completed_runs(_PagingDuplicateAPI(), "acme/repo", 4)

    assert [run["id"] for run in runs] == [4, 3, 2, 1]
    assert len({run["id"] for run in runs}) == len(runs)
