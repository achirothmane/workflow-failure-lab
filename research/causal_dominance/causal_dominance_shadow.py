from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from benchmark_mode import collect_repository_samples, parse_repositories
from ci_retry_gate import FAILURE_CONCLUSIONS, GitHubAPI
from history_ci_waste import HistoricalFailure
from mechanism_causality_gate import MECHANISM_CAUSAL_CONFIRMED
from recovery_ground_truth import (
    RECOVERY_NOT_RECOVERED,
    is_ground_truth_evaluable,
    is_validated_recovery,
)
from root_cause_precedence import (
    DOMINANCE_CANDIDATE,
    DOMINANCE_NO_CAUSAL_SERVER_5XX,
    DOMINANCE_ORDERING_UNPROVEN,
    DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE,
    assess_causal_dominance,
)
from transient_mechanism_gate import REASON_SERVER_5XX


DOMINANCE_LOOKUP_UNRESOLVED = "DOMINANCE_LOOKUP_UNRESOLVED"

DEFAULT_REPOSITORIES = (
    "facebook/react",
    "vercel/next.js",
    "vitejs/vite",
    "webpack/webpack",
    "rollup/rollup",
    "denoland/deno",
    "nodejs/node",
    "oven-sh/bun",
    "microsoft/TypeScript",
    "microsoft/vscode",
    "angular/angular",
    "vuejs/core",
    "sveltejs/svelte",
    "nuxt/nuxt",
    "remix-run/react-router",
    "babel/babel",
    "eslint/eslint",
    "prettier/prettier",
    "pnpm/pnpm",
    "yarnpkg/berry",
    "rust-lang/rust",
    "rust-lang/cargo",
    "tokio-rs/tokio",
    "clap-rs/clap",
    "BurntSushi/ripgrep",
    "starship/starship",
    "helix-editor/helix",
    "fish-shell/fish-shell",
    "nushell/nushell",
    "rustdesk/rustdesk",
    "golang/go",
    "golangci/golangci-lint",
    "gohugoio/hugo",
    "prometheus/prometheus",
    "prometheus/node_exporter",
    "pandas-dev/pandas",
    "numpy/numpy",
    "pytorch/pytorch",
    "huggingface/transformers",
    "huggingface/datasets",
    "scikit-learn/scikit-learn",
    "fastapi/fastapi",
    "django/django",
    "ansible/ansible",
    "saltstack/salt",
    "pytest-dev/pytest",
    "psf/requests",
    "pallets/flask",
    "encode/httpx",
    "psf/black",
)


@dataclass(frozen=True)
class CausalDominanceShadowRecord:
    repository: str
    run_id: int
    attempt: int
    job_name: str
    baseline_category: str
    recovery_status: str
    side_effect_risk: bool
    dominance_status: str
    proposed_category: str = ""
    transient_evidence: tuple[str, ...] = ()
    downstream_evidence: tuple[str, ...] = ()
    blocking_evidence: tuple[str, ...] = ()
    error: str = ""


@dataclass(frozen=True)
class CausalDominanceShadowSummary:
    records: tuple[CausalDominanceShadowRecord, ...]

    @property
    def qualifying(self) -> int:
        return len(self.records)

    @property
    def candidates(self) -> tuple[CausalDominanceShadowRecord, ...]:
        return tuple(
            item for item in self.records
            if item.dominance_status == DOMINANCE_CANDIDATE
        )

    @property
    def evaluable_candidates(self) -> tuple[CausalDominanceShadowRecord, ...]:
        return tuple(
            item for item in self.candidates
            if is_ground_truth_evaluable(item.recovery_status)
        )

    @property
    def validated_recoveries(self) -> int:
        return sum(
            is_validated_recovery(item.recovery_status)
            for item in self.evaluable_candidates
        )

    @property
    def failed_again(self) -> int:
        return sum(
            item.recovery_status == RECOVERY_NOT_RECOVERED
            for item in self.evaluable_candidates
        )

    @property
    def unknown_outcomes(self) -> int:
        return sum(
            not is_ground_truth_evaluable(item.recovery_status)
            for item in self.candidates
        )

    @property
    def observed_precision(self) -> float:
        total = len(self.evaluable_candidates)
        if total <= 0:
            return 0.0
        return self.validated_recoveries / total

    @property
    def authority_safe_validated(self) -> int:
        return sum(
            is_validated_recovery(item.recovery_status)
            and not item.side_effect_risk
            for item in self.evaluable_candidates
        )

    @property
    def primary_deterministic_blocked(self) -> int:
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
    def no_causal_5xx(self) -> int:
        return sum(
            item.dominance_status == DOMINANCE_NO_CAUSAL_SERVER_5XX
            for item in self.records
        )

    @property
    def unresolved(self) -> int:
        return sum(
            item.dominance_status == DOMINANCE_LOOKUP_UNRESOLVED
            for item in self.records
        )

    @property
    def independent_candidate_runs(self) -> int:
        return len({item.run_id for item in self.evaluable_candidates})

    @property
    def independent_candidate_repositories(self) -> int:
        return len({item.repository for item in self.evaluable_candidates})


def _qualifies(item: HistoricalFailure) -> bool:
    return (
        item.category in {"CODE_REGRESSION", "FLAKY_TEST"}
        and item.mechanism_causality_status == MECHANISM_CAUSAL_CONFIRMED
        and REASON_SERVER_5XX in item.mechanism_causality_reasons
    )


def collect_causal_dominance_shadow(
    api: GitHubAPI,
    histories: dict[str, tuple[list[HistoricalFailure], int]],
) -> CausalDominanceShadowSummary:
    records: list[CausalDominanceShadowRecord] = []

    for repository, (failures, _runs) in histories.items():
        for failure in failures:
            if not _qualifies(failure):
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
                    job
                    for job in jobs
                    if str(job.get("name") or "") == failure.job_name
                    and str(job.get("conclusion") or "").lower()
                    in FAILURE_CONCLUSIONS
                ]
                if len(matches) != 1:
                    records.append(
                        CausalDominanceShadowRecord(
                            repository=repository,
                            run_id=failure.run_id,
                            attempt=attempt,
                            job_name=failure.job_name,
                            baseline_category=failure.category,
                            recovery_status=failure.recovery_status,
                            side_effect_risk=failure.side_effect_risk,
                            dominance_status=DOMINANCE_LOOKUP_UNRESOLVED,
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
            except RuntimeError as exc:
                records.append(
                    CausalDominanceShadowRecord(
                        repository=repository,
                        run_id=failure.run_id,
                        attempt=attempt,
                        job_name=failure.job_name,
                        baseline_category=failure.category,
                        recovery_status=failure.recovery_status,
                        side_effect_risk=failure.side_effect_risk,
                        dominance_status=DOMINANCE_LOOKUP_UNRESOLVED,
                        error=str(exc)[:240],
                    )
                )
                continue

            records.append(
                CausalDominanceShadowRecord(
                    repository=repository,
                    run_id=failure.run_id,
                    attempt=attempt,
                    job_name=failure.job_name,
                    baseline_category=failure.category,
                    recovery_status=failure.recovery_status,
                    side_effect_risk=failure.side_effect_risk,
                    dominance_status=dominance.status,
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
            item.attempt,
            item.job_name,
        )
    )
    return CausalDominanceShadowSummary(tuple(records))


def render_causal_dominance_shadow(
    summary: CausalDominanceShadowSummary,
) -> str:
    lines = [
        "## Causal Dominance Shadow Override",
        "",
        "> Research-only counterfactual. No runtime classifier category, retry authority, "
        "or production behavior is changed.",
        "",
        f"- Qualifying causal SERVER_5XX contradictions: **{summary.qualifying}**",
        f"- Dominance candidates: **{len(summary.candidates)}**",
        f"- Ground-truth-evaluable candidates: **{len(summary.evaluable_candidates)}**",
        f"- Validated candidate recoveries: **{summary.validated_recoveries}**",
        f"- Candidate failed again: **{summary.failed_again}**",
        f"- Candidate unknown/unverified outcomes: **{summary.unknown_outcomes}**",
        f"- Observed candidate precision: **{summary.observed_precision:.2%}**",
        f"- Authority-safe validated candidates: **{summary.authority_safe_validated}**",
        f"- Primary deterministic evidence blocked: **{summary.primary_deterministic_blocked}**",
        f"- Ordering unproven: **{summary.ordering_unproven}**",
        f"- Causal 5xx disappeared on raw-log reassessment: **{summary.no_causal_5xx}**",
        f"- Lookup/API unresolved: **{summary.unresolved}**",
        f"- Independent evaluable candidate runs: **{summary.independent_candidate_runs}**",
        f"- Independent evaluable candidate repositories: **{summary.independent_candidate_repositories}**",
        "",
        "### Candidate details",
        "",
        "| Repository | Run | Job | Baseline | Proposed | Outcome | Side effect |",
        "|---|---:|---|---|---|---|---|",
    ]
    for item in summary.candidates:
        lines.append(
            f"| {item.repository} | {item.run_id} | {item.job_name.replace('|', '/')} | "
            f"`{item.baseline_category}` | `{item.proposed_category or '—'}` | "
            f"`{item.recovery_status}` | "
            f"{'yes' if item.side_effect_risk else 'no'} |"
        )
    if not summary.candidates:
        lines.append("| — | — | — | — | — | — | — |")

    if summary.primary_deterministic_blocked:
        lines.extend(["", "### Deterministic blockers", ""])
        for item in summary.records:
            if item.dominance_status != DOMINANCE_PRIMARY_DETERMINISTIC_EVIDENCE:
                continue
            evidence = " / ".join(item.blocking_evidence[:2]) or "strong deterministic evidence"
            lines.append(
                f"- {item.repository} run {item.run_id}, job {item.job_name}: "
                f"{evidence.replace('|', '/')}"
            )

    if summary.unresolved:
        lines.extend(["", "### Unresolved lookups", ""])
        for item in summary.records:
            if item.dominance_status == DOMINANCE_LOOKUP_UNRESOLVED:
                lines.append(
                    f"- {item.repository} run {item.run_id}, job {item.job_name}: "
                    f"{item.error.replace('|', '/')}"
                )

    lines.extend(
        [
            "",
            "> A candidate is not a production override. Promotion requires separate "
            "evidence review and must not bypass side-effect, provenance, attempt-cap, "
            "or other authority boundaries.",
        ]
    )
    return "\n".join(lines) + "\n"


def shadow_summary_payload(
    summary: CausalDominanceShadowSummary,
    *,
    repositories_requested: int,
    repositories_analyzed: int,
    repositories_skipped: int,
) -> dict[str, object]:
    return {
        "repositories_requested": repositories_requested,
        "repositories_analyzed": repositories_analyzed,
        "repositories_skipped": repositories_skipped,
        "qualifying": summary.qualifying,
        "dominance_candidates": len(summary.candidates),
        "evaluable_candidates": len(summary.evaluable_candidates),
        "validated_candidate_recoveries": summary.validated_recoveries,
        "candidate_failed_again": summary.failed_again,
        "candidate_unknown_outcomes": summary.unknown_outcomes,
        "observed_candidate_precision": summary.observed_precision,
        "authority_safe_validated_candidates": summary.authority_safe_validated,
        "primary_deterministic_blocked": summary.primary_deterministic_blocked,
        "ordering_unproven": summary.ordering_unproven,
        "no_causal_5xx": summary.no_causal_5xx,
        "unresolved": summary.unresolved,
        "independent_candidate_runs": summary.independent_candidate_runs,
        "independent_candidate_repositories": summary.independent_candidate_repositories,
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
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("::error::github-token is required")
        return 2

    raw_repositories = os.environ.get("INPUT_DOMINANCE_REPOSITORIES", "").strip()
    repositories = (
        parse_repositories(raw_repositories)
        if raw_repositories
        else list(DEFAULT_REPOSITORIES)
    )
    rerun_run_limit = max(
        1,
        min(int(os.environ.get("INPUT_DOMINANCE_RERUN_RUNS", "50")), 50),
    )
    rerun_search_limit = max(
        rerun_run_limit,
        min(int(os.environ.get("INPUT_DOMINANCE_SEARCH_RUNS", "500")), 500),
    )
    workers = max(
        1,
        min(int(os.environ.get("INPUT_DOMINANCE_WORKERS", "5")), 10),
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

    summary = collect_causal_dominance_shadow(GitHubAPI(token), histories)
    report = render_causal_dominance_shadow(summary)
    report += "\n## Collection\n\n"
    report += f"- Repositories requested: **{len(repositories)}**\n"
    report += f"- Repositories analyzed: **{len(histories)}**\n"
    report += f"- Repositories skipped: **{len(skipped)}**\n"
    if skipped:
        report += "\n### Skipped repositories\n\n"
        for repository, error in sorted(skipped):
            report += f"- `{repository}` — {error.replace('|', '/')}\n"

    result_path = os.environ.get("INPUT_DOMINANCE_RESULT_PATH", "").strip()
    if result_path:
        payload = shadow_summary_payload(
            summary,
            repositories_requested=len(repositories),
            repositories_analyzed=len(histories),
            repositories_skipped=len(skipped),
        )
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
