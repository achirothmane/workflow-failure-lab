from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmark_mode import collect_repository_samples
from ci_retry_gate import FAILURE_CONCLUSIONS, GitHubAPI, detect_side_effect_risk
from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)
from root_cause_precedence import (
    DOMINANCE_CANDIDATE,
    DOMINANCE_ORDERING_UNPROVEN,
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
    assess_causal_dominance,
)
from transient_mechanism_gate import REASON_SERVER_5XX


SEARCH_SHARDS: dict[int, tuple[str, ...]] = {
    1: (
        "microsoft/playwright",
        "microsoft/terminal",
        "microsoft/fluentui",
        "microsoft/monaco-editor",
        "electron/electron",
        "storybookjs/storybook",
        "mui/material-ui",
        "chakra-ui/chakra-ui",
        "ant-design/ant-design",
        "vercel/turborepo",
        "nrwl/nx",
        "nestjs/nest",
        "expressjs/express",
        "fastify/fastify",
        "koajs/koa",
        "axios/axios",
        "prisma/prisma",
        "sequelize/sequelize",
        "typeorm/typeorm",
        "trpc/trpc",
        "reduxjs/redux-toolkit",
        "TanStack/query",
        "TanStack/router",
        "vitest-dev/vitest",
        "jestjs/jest",
        "testing-library/dom-testing-library",
        "testing-library/react-testing-library",
        "getsentry/sentry-javascript",
        "elastic/kibana",
        "grafana/grafana",
        "home-assistant/frontend",
        "firebase/firebase-js-sdk",
        "aws-amplify/amplify-js",
        "aws/aws-cdk",
        "serverless/serverless",
        "apollographql/apollo-client",
        "graphql/graphql-js",
        "facebook/docusaurus",
        "vuejs/vitepress",
        "withastro/astro",
        "ionic-team/ionic-framework",
        "capacitor-community/sqlite",
        "angular/components",
        "nodejs/undici",
        "nodejs/corepack",
        "npm/cli",
        "npm/node-semver",
        "eslint/eslintrc",
        "rollup/plugins",
        "babel/babel-jest",
    ),
    2: (
        "pydantic/pydantic",
        "encode/starlette",
        "astral-sh/ruff",
        "astral-sh/uv",
        "sqlfluff/sqlfluff",
        "pallets/click",
        "pallets/jinja",
        "pyca/cryptography",
        "python-pillow/Pillow",
        "scikit-image/scikit-image",
        "matplotlib/matplotlib",
        "pydata/xarray",
        "jupyterlab/jupyterlab",
        "jupyter/notebook",
        "ipython/ipython",
        "spyder-ide/spyder",
        "pypa/setuptools",
        "pypa/build",
        "pypa/twine",
        "pypa/pipx",
        "tox-dev/tox",
        "pytest-dev/pluggy",
        "pytest-dev/pytest-xdist",
        "python/mypy",
        "python/typeshed",
        "python-trio/trio",
        "agronholm/anyio",
        "aio-libs/yarl",
        "MagicStack/uvloop",
        "Textualize/rich",
        "Textualize/textual",
        "tiangolo/sqlmodel",
        "sqlalchemy/sqlalchemy",
        "mongodb/mongo-python-driver",
        "redis/redis-py",
        "boto/boto3",
        "aws/aws-cli",
        "googleapis/google-cloud-python",
        "grpc/grpc",
        "tensorflow/tensorflow",
        "Lightning-AI/pytorch-lightning",
        "optuna/optuna",
        "wandb/wandb",
        "onnx/onnx",
        "openai/triton",
        "pola-rs/polars",
        "rapidsai/cudf",
        "apache/mxnet",
        "huggingface/tokenizers",
        "huggingface/safetensors",
        "rust-lang/rustup",
    ),
}


@dataclass(frozen=True)
class PositiveSearchRecord:
    repository: str
    run_id: int
    attempt: int
    job_name: str
    baseline_history_category: str
    recovery_status: str
    raw_side_effect_risk: bool
    dominance_status: str
    raw_baseline_category: str
    proposed_category: str
    transient_evidence: tuple[str, ...] = ()
    downstream_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()
    error: str = ""

    @property
    def validated_positive(self) -> bool:
        return (
            self.dominance_status == DOMINANCE_CANDIDATE
            and is_validated_recovery(self.recovery_status)
            and not self.raw_side_effect_risk
        )

    @property
    def failed_again_counterexample(self) -> bool:
        return (
            self.dominance_status == DOMINANCE_CANDIDATE
            and self.recovery_status == RECOVERY_NOT_RECOVERED
        )


@dataclass(frozen=True)
class PositiveSearchSummary:
    records: tuple[PositiveSearchRecord, ...]
    repositories_requested: int
    repositories_analyzed: int
    repositories_skipped: int

    @property
    def dominance_candidates(self) -> tuple[PositiveSearchRecord, ...]:
        return tuple(
            item for item in self.records
            if item.dominance_status == DOMINANCE_CANDIDATE
        )

    @property
    def validated_positives(self) -> tuple[PositiveSearchRecord, ...]:
        return tuple(item for item in self.records if item.validated_positive)

    @property
    def failed_again(self) -> tuple[PositiveSearchRecord, ...]:
        return tuple(
            item for item in self.records
            if item.failed_again_counterexample
        )

    @property
    def independent_positive_runs(self) -> int:
        return len({item.run_id for item in self.validated_positives})

    @property
    def independent_positive_repositories(self) -> int:
        return len({item.repository for item in self.validated_positives})

    @property
    def blocked_deterministic(self) -> int:
        return sum(
            item.dominance_status == DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE
            for item in self.records
        )

    @property
    def ordering_unproven(self) -> int:
        return sum(
            item.dominance_status == DOMINANCE_ORDERING_UNPROVEN
            for item in self.records
        )

    @property
    def unresolved(self) -> int:
        return sum(bool(item.error) for item in self.records)


def _qualifies_history(item: HistoricalFailure) -> bool:
    return (
        item.category in {"CODE_REGRESSION", "FLAKY_TEST"}
        and item.mechanism_causality_status == MECHANISM_CAUSAL_CONFIRMED
        and REASON_SERVER_5XX in item.mechanism_causality_reasons
        and is_ground_truth_evaluable(item.recovery_status)
    )


def search_positive_controls(
    api: GitHubAPI,
    histories: dict[str, tuple[list[HistoricalFailure], int]],
    *,
    repositories_requested: int | None = None,
    repositories_skipped: int = 0,
) -> PositiveSearchSummary:
    records: list[PositiveSearchRecord] = []

    for repository, (failures, _runs) in histories.items():
        for failure in failures:
            if not _qualifies_history(failure):
                continue

            attempt = max(1, int(failure.attempt or 1))
            try:
                data = api.request(
                    "GET",
                    f"/repos/{repository}/actions/runs/{failure.run_id}"
                    f"/attempts/{attempt}/jobs?per_page=100",
                )
                jobs = list(data.get("jobs") or [])
                matches = [
                    job for job in jobs
                    if str(job.get("name") or "") == failure.job_name
                    and str(job.get("conclusion") or "").lower()
                    in FAILURE_CONCLUSIONS
                ]
                if len(matches) != 1:
                    records.append(
                        PositiveSearchRecord(
                            repository=repository,
                            run_id=failure.run_id,
                            attempt=attempt,
                            job_name=failure.job_name,
                            baseline_history_category=failure.category,
                            recovery_status=failure.recovery_status,
                            raw_side_effect_risk=True,
                            dominance_status="LOOKUP_UNRESOLVED",
                            raw_baseline_category="",
                            proposed_category="",
                            error=f"job_match_count={len(matches)}",
                        )
                    )
                    continue

                job = matches[0]
                log_text = api.get_job_logs(
                    repository,
                    int(job.get("id") or 0),
                )
                dominance = assess_causal_dominance(job, log_text)
                side_effect_risk, _ = detect_side_effect_risk(job)
            except RuntimeError as exc:
                records.append(
                    PositiveSearchRecord(
                        repository=repository,
                        run_id=failure.run_id,
                        attempt=attempt,
                        job_name=failure.job_name,
                        baseline_history_category=failure.category,
                        recovery_status=failure.recovery_status,
                        raw_side_effect_risk=True,
                        dominance_status="LOOKUP_UNRESOLVED",
                        raw_baseline_category="",
                        proposed_category="",
                        error=str(exc)[:300],
                    )
                )
                continue

            records.append(
                PositiveSearchRecord(
                    repository=repository,
                    run_id=failure.run_id,
                    attempt=attempt,
                    job_name=failure.job_name,
                    baseline_history_category=failure.category,
                    recovery_status=failure.recovery_status,
                    raw_side_effect_risk=side_effect_risk,
                    dominance_status=dominance.status,
                    raw_baseline_category=dominance.baseline_category,
                    proposed_category=dominance.proposed_category,
                    transient_evidence=dominance.transient_evidence,
                    downstream_evidence=dominance.downstream_evidence,
                    blocking_evidence=dominance.blocking_evidence,
                )
            )

    records.sort(
        key=lambda item: (
            item.repository,
            item.run_id,
            item.job_name,
        )
    )
    return PositiveSearchSummary(
        records=tuple(records),
        repositories_requested=(
            repositories_requested
            if repositories_requested is not None
            else len(histories)
        ),
        repositories_analyzed=len(histories),
        repositories_skipped=repositories_skipped,
    )


def render_positive_search(summary: PositiveSearchSummary) -> str:
    lines = [
        "## Causal Dominance Targeted Positive-Control Search",
        "",
        "> Read-only targeted search. No production classifier or retry authority is changed.",
        "",
        f"- Repositories requested: **{summary.repositories_requested}**",
        f"- Repositories analyzed: **{summary.repositories_analyzed}**",
        f"- Repositories skipped: **{summary.repositories_skipped}**",
        f"- Ground-truth-evaluable non-transient SERVER_5XX cases inspected: **{len(summary.records)}**",
        f"- Dominance candidates: **{len(summary.dominance_candidates)}**",
        f"- Authority-safe validated positives: **{len(summary.validated_positives)}**",
        f"- Candidate failed-again counterexamples: **{len(summary.failed_again)}**",
        f"- Independent validated positive runs: **{summary.independent_positive_runs}**",
        f"- Independent validated positive repositories: **{summary.independent_positive_repositories}**",
        f"- Deterministic blockers: **{summary.blocked_deterministic}**",
        f"- Ordering unproven: **{summary.ordering_unproven}**",
        f"- Lookup/API unresolved: **{summary.unresolved}**",
        "",
        "### Validated positive-control candidates",
        "",
        "| Repository | Run | Job | History | Raw baseline | Outcome |",
        "|---|---:|---|---|---|---|",
    ]
    for item in summary.validated_positives:
        lines.append(
            f"| {item.repository} | {item.run_id} | {item.job_name.replace('|', '/')} | "
            f"`{item.baseline_history_category}` | `{item.raw_baseline_category}` | "
            f"`{item.recovery_status}` |"
        )
    if not summary.validated_positives:
        lines.append("| — | — | — | — | — | No validated positive found |")

    if summary.failed_again:
        lines.extend(["", "### Failed-again falsifiers", ""])
        for item in summary.failed_again:
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}"
            )

    if summary.records:
        lines.extend(["", "### All inspected cases", ""])
        for item in summary.records:
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}: "
                f"history={item.baseline_history_category}, raw={item.raw_baseline_category or '—'}, "
                f"dominance={item.dominance_status}, outcome={item.recovery_status}, "
                f"side_effect={'yes' if item.raw_side_effect_risk else 'no'}"
            )
    return "\n".join(lines) + "\n"


def summary_payload(summary: PositiveSearchSummary) -> dict[str, object]:
    return {
        "repositories_requested": summary.repositories_requested,
        "repositories_analyzed": summary.repositories_analyzed,
        "repositories_skipped": summary.repositories_skipped,
        "cases_inspected": len(summary.records),
        "dominance_candidates": len(summary.dominance_candidates),
        "validated_positives": len(summary.validated_positives),
        "failed_again": len(summary.failed_again),
        "independent_positive_runs": summary.independent_positive_runs,
        "independent_positive_repositories": summary.independent_positive_repositories,
        "blocked_deterministic": summary.blocked_deterministic,
        "ordering_unproven": summary.ordering_unproven,
        "unresolved": summary.unresolved,
        "validated_positive_records": [
            asdict(item) for item in summary.validated_positives
        ],
        "failed_again_records": [
            asdict(item) for item in summary.failed_again
        ],
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=int, choices=sorted(SEARCH_SHARDS), required=True)
    parser.add_argument("--result-json", type=Path)
    args = parser.parse_args()

    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("::error::github-token is required")
        return 2

    repositories = list(SEARCH_SHARDS[args.shard])
    rerun_run_limit = max(
        1,
        min(int(os.environ.get("INPUT_POSITIVE_SEARCH_RERUN_RUNS", "50")), 50),
    )
    rerun_search_limit = max(
        rerun_run_limit,
        min(int(os.environ.get("INPUT_POSITIVE_SEARCH_HISTORY_RUNS", "500")), 500),
    )
    workers = max(
        1,
        min(int(os.environ.get("INPUT_POSITIVE_SEARCH_WORKERS", "5")), 8),
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
    report = render_positive_search(summary)

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
        args.result_json.write_text(
            json.dumps(summary_payload(summary), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
