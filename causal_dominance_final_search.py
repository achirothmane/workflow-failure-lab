from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from benchmark_mode import collect_repository_samples
from causal_dominance_positive_search import (
    render_positive_search,
    search_positive_controls,
    summary_payload,
)
from causal_dominance_shadow import DEFAULT_REPOSITORIES
from ci_retry_gate import GitHubAPI
from history_ci_waste import HistoricalFailure


FINAL_SEARCH_SHARDS: dict[int, tuple[str, ...]] = {
    1: (
        "microsoft/azure-pipelines-tasks",
        "microsoft/FluidFramework",
        "microsoft/vscode-eslint",
        "microsoft/pyright",
        "microsoft/PowerToys",
        "denoland/fresh",
        "expo/expo",
        "facebook/react-native",
        "react-hook-form/react-hook-form",
        "colinhacks/zod",
        "drizzle-team/drizzle-orm",
        "payloadcms/payload",
        "strapi/strapi",
        "directus/directus",
        "supabase/supabase",
        "appwrite/appwrite",
        "n8n-io/n8n",
        "hoppscotch/hoppscotch",
        "PostHog/posthog",
        "cypress-io/cypress",
        "webdriverio/webdriverio",
        "puppeteer/puppeteer",
        "nodejs/readable-stream",
        "socketio/socket.io",
        "biomejs/biome",
        "celery/celery",
        "pallets/werkzeug",
        "pallets/itsdangerous",
        "python-poetry/poetry",
        "python-poetry/cleo",
        "scipy/scipy",
        "sympy/sympy",
        "networkx/networkx",
        "apache/airflow",
        "PrefectHQ/prefect",
        "dagster-io/dagster",
        "ray-project/ray",
        "mlflow/mlflow",
        "kedro-org/kedro",
        "scrapy/scrapy",
        "home-assistant/core",
        "urllib3/urllib3",
        "aio-libs/aiohttp",
        "encode/uvicorn",
        "httpie/cli",
        "mitmproxy/mitmproxy",
        "locustio/locust",
        "sphinx-doc/sphinx",
        "mkdocs/mkdocs",
        "rust-lang/rustfmt",
    ),
    2: (
        "rust-lang/mdBook",
        "serde-rs/json",
        "rayon-rs/rayon",
        "crossbeam-rs/crossbeam",
        "seanmonstar/reqwest",
        "hyperium/hyper",
        "tower-rs/tower",
        "tokio-rs/axum",
        "diesel-rs/diesel",
        "launchbadge/sqlx",
        "tauri-apps/tauri",
        "bevyengine/bevy",
        "alacritty/alacritty",
        "sharkdp/bat",
        "sharkdp/fd",
        "jdx/mise",
        "kubernetes/kubernetes",
        "kubernetes-sigs/controller-runtime",
        "kubernetes-sigs/kind",
        "etcd-io/etcd",
        "containerd/containerd",
        "moby/moby",
        "docker/cli",
        "docker/buildx",
        "helm/helm",
        "hashicorp/terraform",
        "hashicorp/vault",
        "hashicorp/nomad",
        "go-gitea/gitea",
        "cli/cli",
        "spf13/cobra",
        "gin-gonic/gin",
        "go-chi/chi",
        "labstack/echo",
        "cockroachdb/cockroach",
        "grafana/loki",
        "grafana/tempo",
        "caddyserver/caddy",
        "spring-projects/spring-boot",
        "spring-projects/spring-framework",
        "gradle/gradle",
        "apache/maven",
        "junit-team/junit5",
        "mockito/mockito",
        "quarkusio/quarkus",
        "micronaut-projects/micronaut-core",
        "elastic/elasticsearch",
        "opensearch-project/OpenSearch",
        "apache/kafka",
        "apache/flink",
    ),
}


def _collect_repository(
    token: str,
    repository: str,
    rerun_run_limit: int,
    rerun_search_limit: int,
) -> tuple[str, tuple[list[HistoricalFailure], int] | None, str | None]:
    api = GitHubAPI(token)
    try:
        _natural, enriched = collect_repository_samples(
            api,
            repository,
            0,
            rerun_run_limit,
            rerun_search_limit,
        )
        return repository, enriched, None
    except RuntimeError as exc:
        return repository, None, str(exc)[:300]


def validate_final_search_corpus() -> tuple[bool, str]:
    all_repositories = [
        repository
        for shard in FINAL_SEARCH_SHARDS.values()
        for repository in shard
    ]
    if set(FINAL_SEARCH_SHARDS) != {1, 2}:
        return False, "expected exactly shards 1 and 2"
    if any(len(shard) != 50 for shard in FINAL_SEARCH_SHARDS.values()):
        return False, "each final shard must contain exactly 50 repositories"
    if len(set(all_repositories)) != 100:
        return False, "final search repositories must be unique"

    from causal_dominance_positive_search import SEARCH_SHARDS

    prior = {
        repository
        for shard in SEARCH_SHARDS.values()
        for repository in shard
    }
    prior.update(DEFAULT_REPOSITORIES)
    overlap = sorted(set(all_repositories) & prior)
    if overlap:
        return False, "overlap with prior search/holdout: " + ", ".join(overlap)
    return True, "100 unique repositories with no prior search/holdout overlap"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shard",
        type=int,
        choices=sorted(FINAL_SEARCH_SHARDS),
        required=True,
    )
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    corpus_ok, corpus_reason = validate_final_search_corpus()
    if not corpus_ok:
        print(f"::error::final search corpus invalid: {corpus_reason}")
        return 2

    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("::error::github-token is required")
        return 2

    repositories = list(FINAL_SEARCH_SHARDS[args.shard])
    rerun_run_limit = max(
        1,
        min(int(os.environ.get("INPUT_FINAL_SEARCH_RERUN_RUNS", "50")), 50),
    )
    rerun_search_limit = max(
        rerun_run_limit,
        min(int(os.environ.get("INPUT_FINAL_SEARCH_HISTORY_RUNS", "500")), 500),
    )
    workers = max(
        1,
        min(int(os.environ.get("INPUT_FINAL_SEARCH_WORKERS", "5")), 8),
    )

    histories: dict[str, tuple[list[HistoricalFailure], int]] = {}
    skipped: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _collect_repository,
                token,
                repository,
                rerun_run_limit,
                rerun_search_limit,
            )
            for repository in repositories
        ]
        for future in as_completed(futures):
            repository, enriched, error = future.result()
            if error or enriched is None:
                skipped.append((repository, error or "unknown collection failure"))
            else:
                histories[repository] = enriched

    summary = search_positive_controls(
        GitHubAPI(token),
        histories,
        repositories_requested=len(repositories),
        repositories_skipped=len(skipped),
    )
    report = "## Final Independent Positive-Control Search\n\n"
    report += (
        "> Goal: find the one remaining independent real causal-dominance positive "
        "without reusing earlier targeted-search or 50-repository holdout repos.\n\n"
    )
    report += f"- Corpus integrity: **{corpus_reason}**\n"
    report += f"- Shard: **{args.shard}/2**\n\n"
    report += render_positive_search(summary)

    if skipped:
        report += "\n### Skipped repositories\n\n"
        for repository, error in sorted(skipped):
            report += f"- `{repository}` — {error.replace('|', '/')}\n"

    print(report)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)

    if args.result_json:
        payload = summary_payload(summary)
        payload["shard"] = args.shard
        payload["corpus_integrity"] = corpus_reason
        args.result_json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
