from __future__ import annotations

import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

TRANSIENT_CATEGORIES = {"RUNNER_INFRA", "DEPENDENCY_NETWORK"}
FAILURE_CONCLUSIONS = {"failure", "timed_out", "cancelled"}

_SECRET_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+\-/]+=*"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s]+"),
]

# GitHub logs can contain terminal color/control sequences inside error lines.
# Strip them before matching so operational signatures are not split by escape bytes.
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_RUNNER_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+"
)

_CATEGORY_RULES: dict[str, tuple[tuple[int, re.Pattern[str]], ...]] = {
    "RUNNER_INFRA": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"lost communication with the server"),
            (5, r"runner .* (lost|stopped|shutdown|disconnected)"),
            (5, r"hosted runner .* (shutdown|unavailable|failed)"),
            (4, r"the runner has received a shutdown signal"),
            (4, r"failed to start (the )?(virtual machine|runner)"),
            (3, r"internal server error"),
            (3, r"service unavailable"),
        ]
    ),
    "DEPENDENCY_NETWORK": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"temporary failure in name resolution"),
            (5, r"could not resolve host"),
            (5, r"econnreset|etimedout|eai_again"),
            (4, r"connection reset by peer"),
            (4, r"tls handshake timeout"),
            (4, r"network is unreachable"),
            (3, r"\b429\b.*too many requests|too many requests.*\b429\b"),
            (3, r"\b502\b.*bad gateway|\b503\b.*service unavailable|\b504\b.*gateway timeout"),
            (2, r"connection timed out|read timed out|connect timeout"),
        ]
    ),
    "RESOURCE_TIMEOUT": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"process completed with exit code 137"),
            (5, r"out of memory|oomkilled|cannot allocate memory"),
            (4, r"no space left on device"),
            (3, r"exceeded.*time limit|job .* timed out|operation timed out"),
        ]
    ),
    "FLAKY_TEST": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (5, r"flaky test|test .* marked flaky"),
            (4, r"passed on retry|passed after retry"),
            (3, r"retrying test|rerun.*test"),
        ]
    ),
    "CODE_REGRESSION": tuple(
        (weight, re.compile(pattern, re.IGNORECASE))
        for weight, pattern in [
            (4, r"assertionerror|assertion failed"),
            (4, r"syntaxerror|typeerror|referenceerror|compile error|compilation failed"),
            (3, r"tests? failed|failing tests?|test failure"),
            (3, r"lint(ing)? failed|type.?check.*failed"),
            (2, r"process completed with exit code [1-9][0-9]*"),
        ]
    ),
}

# These signatures are intentionally narrower than the scoring rules above.
# A single occurrence may be enough for high confidence only when it looks like
# an operational failure emitted by a network/client stack, rather than prose,
# documentation, a source fixture, or a generic timeout word.
_HIGH_SPECIFICITY_TRANSIENT_RULES: dict[str, tuple[re.Pattern[str], ...]] = {
    "RUNNER_INFRA": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"lost communication with the server",
            r"the runner has received a shutdown signal",
            r"hosted runner .* (shutdown|unavailable|failed)",
        ]
    ),
    "DEPENDENCY_NETWORK": tuple(
        re.compile(pattern, re.IGNORECASE)
        for pattern in [
            r"\bnpm (?:err!|error) code (?:econnreset|etimedout|eai_again)\b",
            r"\bread tcp\b.*\bread:\s*connection reset by peer\b",
            r"\bdial tcp\b.*(?:i/o timeout|connect:\s*(?:connection timed out|network is unreachable|connection refused))",
            r"\bcurl:\s*\((?:6|7|28|35|56)\)\b",
            r"\bfatal: unable to access\b.*(?:could not resolve host|recv failure: connection reset by peer|failed to connect|operation timed out)",
            r"\b(?:error|fatal):\s*connection reset by peer\b",
            r"\bconnect etimedout\b",
            r"\btls handshake timeout\b",
        ]
    ),
}

_SIDE_EFFECT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bdeploy(?:ment|ing)?\b",
        r"\bpublish(?:ing)?\b",
        r"\brelease\b",
        r"\bterraform\s+apply\b",
        r"\bkubectl\s+apply\b",
        r"\bhelm\s+(upgrade|install)\b",
        r"\bmigrat(?:e|ion|ing)\b",
        r"\bdatabase\s+(write|update|seed)\b",
        r"\bpush\s+image\b",
        r"\bnpm\s+publish\b",
        r"\bpypi\b",
    ]
)


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: str
    score: int
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class JobAssessment:
    job_id: int
    name: str
    category: str
    confidence: str
    evidence: tuple[str, ...]
    side_effect_risk: bool
    side_effect_evidence: tuple[str, ...]
    duration_minutes: float


def redact(text: str) -> str:
    value = text
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", value)
    return value


def _useful_line(line: str) -> str:
    line = _ANSI_ESCAPE_RE.sub("", redact(line))
    line = _RUNNER_TIMESTAMP_RE.sub("", line).strip()
    if len(line) > 300:
        line = line[:297] + "..."
    return line


def classify_log(log_text: str) -> Classification:
    scores: dict[str, int] = {name: 0 for name in _CATEGORY_RULES}
    evidence: dict[str, list[str]] = {name: [] for name in _CATEGORY_RULES}
    strong_transient_evidence: dict[str, list[str]] = {
        name: [] for name in _HIGH_SPECIFICITY_TRANSIENT_RULES
    }

    seen_lines: set[str] = set()
    for raw_line in log_text.splitlines():
        line = _useful_line(raw_line)
        if not line or line in seen_lines:
            continue
        seen_lines.add(line)
        for category, rules in _CATEGORY_RULES.items():
            for weight, pattern in rules:
                if pattern.search(line):
                    scores[category] += weight
                    if len(evidence[category]) < 3 and line not in evidence[category]:
                        evidence[category].append(line)
                    break
        for category, patterns in _HIGH_SPECIFICITY_TRANSIENT_RULES.items():
            if any(pattern.search(line) for pattern in patterns):
                if len(strong_transient_evidence[category]) < 3 and line not in strong_transient_evidence[category]:
                    strong_transient_evidence[category].append(line)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_category, top_score = ranked[0]
    second_score = ranked[1][1]

    if top_score < 3:
        return Classification("UNKNOWN", "low", top_score, tuple())

    margin = top_score - second_score
    if top_score >= 7 and margin >= 3:
        confidence = "high"
    elif top_score >= 4 and margin >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    if (
        top_category in TRANSIENT_CATEGORIES
        and strong_transient_evidence.get(top_category)
        and second_score <= 2
    ):
        confidence = "high"

    if top_category == "CODE_REGRESSION" and top_score < 7:
        confidence = "medium" if top_score >= 4 else "low"

    return Classification(top_category, confidence, top_score, tuple(evidence[top_category]))


def detect_side_effect_risk(job: dict) -> tuple[bool, tuple[str, ...]]:
    hits: list[str] = []
    candidates = [str(job.get("name") or "")]
    for step in job.get("steps") or []:
        candidates.append(str(step.get("name") or ""))

    for candidate in candidates:
        for pattern in _SIDE_EFFECT_PATTERNS:
            if pattern.search(candidate):
                cleaned = _useful_line(candidate)
                if cleaned and cleaned not in hits:
                    hits.append(cleaned)
                break
    return bool(hits), tuple(hits[:3])


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def job_duration_minutes(job: dict) -> float:
    start = _parse_time(job.get("started_at"))
    end = _parse_time(job.get("completed_at"))
    if start is None or end is None or end < start:
        return 0.0
    return round((end - start).total_seconds() / 60.0, 2)


def assess_job(job: dict, log_text: str) -> JobAssessment:
    classification = classify_log(log_text)
    side_effect_risk, side_effect_evidence = detect_side_effect_risk(job)
    return JobAssessment(
        job_id=int(job.get("id") or 0),
        name=str(job.get("name") or f"job-{job.get('id', 'unknown')}"),
        category=classification.category,
        confidence=classification.confidence,
        evidence=classification.evidence,
        side_effect_risk=side_effect_risk,
        side_effect_evidence=side_effect_evidence,
        duration_minutes=job_duration_minutes(job),
    )


def rerun_decision(assessments: Iterable[JobAssessment], run_attempt: int, max_attempts: int) -> tuple[bool, str]:
    items = list(assessments)
    if not items:
        return False, "No failed jobs were available to assess."
    if run_attempt >= max_attempts:
        return False, f"Run attempt {run_attempt} reached max_attempts={max_attempts}."
    if any(item.side_effect_risk for item in items):
        return False, "At least one failed job contains a side-effect signal; blind rerun is blocked."
    unsafe = [
        item for item in items
        if item.category not in TRANSIENT_CATEGORIES or item.confidence != "high"
    ]
    if unsafe:
        names = ", ".join(f"{item.name}={item.category}/{item.confidence}" for item in unsafe)
        return False, f"Not every failed job is a high-confidence transient failure: {names}."
    return True, "All failed jobs are high-confidence transient failures and no side-effect signal was found."


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow GitHub log redirects without forwarding the bearer token cross-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urlparse(req.full_url).netloc
        new_host = urlparse(newurl).netloc
        if old_host and new_host and old_host != new_host:
            redirected.remove_header("Authorization")
        return redirected


class GitHubAPI:
    def __init__(self, token: str, api_url: str = "https://api.github.com"):
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.opener = urllib.request.build_opener(_SafeRedirectHandler())

    def request(self, method: str, path: str, payload: dict | None = None, accept: str = "application/vnd.github+json"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        attempts = 3 if method.upper() == "GET" else 1
        last_transport_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(
                f"{self.api_url}{path}",
                data=data,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": accept,
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "ci-retry-gate-action",
                    "Content-Type": "application/json",
                },
            )
            try:
                with self.opener.open(req, timeout=30) as response:
                    body = response.read()
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type:
                        return json.loads(body.decode("utf-8"))
                    return body.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"GitHub API {method} {path} failed with HTTP {exc.code}: {body[:500]}"
                ) from exc
            except (
                http.client.IncompleteRead,
                http.client.RemoteDisconnected,
                ConnectionResetError,
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_transport_error = exc
                if attempt >= attempts:
                    break
                time.sleep(0.25 * attempt)

        raise RuntimeError(
            f"GitHub API {method} {path} failed after {attempts} transport attempts: "
            f"{type(last_transport_error).__name__}: {last_transport_error}"
        ) from last_transport_error

    def get_run(self, repo: str, run_id: int) -> dict:
        return self.request("GET", f"/repos/{repo}/actions/runs/{run_id}")

    def get_jobs(self, repo: str, run_id: int) -> list[dict]:
        data = self.request("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs?per_page=100")
        return list(data.get("jobs") or [])

    def get_job_logs(self, repo: str, job_id: int) -> str:
        return str(self.request("GET", f"/repos/{repo}/actions/jobs/{job_id}/logs", accept="application/vnd.github+json"))

    def rerun_failed_jobs(self, repo: str, run_id: int) -> None:
        self.request("POST", f"/repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs", payload={})

    def post_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        self.request("POST", f"/repos/{repo}/issues/{pr_number}/comments", payload={"body": body})


def _event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _write_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def render_report(repo: str, run_id: int, run_attempt: int, assessments: list[JobAssessment], safe: bool, reason: str, rerun_triggered: bool) -> str:
    wasted = round(sum(item.duration_minutes for item in assessments), 2)
    lines = [
        "<!-- ci-retry-gate-report -->",
        "## CI Retry Gate",
        "",
        f"Repository: `{repo}` · Run: `{run_id}` · Attempt: `{run_attempt}`",
        "",
        f"**Decision:** {'SAFE TO RERUN' if safe else 'DO NOT AUTO-RERUN'}",
        "",
        f"{reason}",
        "",
        f"Failed-job runtime observed: **{wasted:.2f} min**",
        "",
        "| Job | Classification | Confidence | Side-effect risk | Runtime |",
        "|---|---|---|---|---:|",
    ]
    for item in assessments:
        lines.append(
            f"| {item.name.replace('|', '/')} | `{item.category}` | {item.confidence} | "
            f"{'YES' if item.side_effect_risk else 'no'} | {item.duration_minutes:.2f} min |"
        )
    for item in assessments:
        lines.extend(["", f"### {item.name}"])
        if item.evidence:
            lines.append("Evidence:")
            for evidence in item.evidence:
                lines.append(f"- `{evidence.replace('`', "'")}`")
        else:
            lines.append("- No strong signature found in the available log.")
        if item.side_effect_evidence:
            lines.append("Side-effect signals:")
            for evidence in item.side_effect_evidence:
                lines.append(f"- `{evidence.replace('`', "'")}`")
    lines.extend(["", f"Automatic rerun triggered: **{'yes' if rerun_triggered else 'no'}**"])
    return "\n".join(lines) + "\n"


def main() -> int:
    token = os.environ.get("INPUT_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("INPUT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY")
    event = _event_payload()
    workflow_run = event.get("workflow_run") or {}
    run_id_raw = os.environ.get("INPUT_RUN_ID") or workflow_run.get("id") or os.environ.get("GITHUB_RUN_ID")

    if not token:
        print("::error::github-token is required")
        return 2
    if not repo:
        print("::error::repository could not be determined")
        return 2
    try:
        run_id = int(run_id_raw)
    except (TypeError, ValueError):
        print("::error::run-id could not be determined")
        return 2

    max_attempts = int(os.environ.get("INPUT_MAX_ATTEMPTS", "2"))
    auto_rerun = _bool_env("INPUT_AUTO_RERUN", False)
    comment_on_pr = _bool_env("INPUT_COMMENT_ON_PR", True)

    api = GitHubAPI(token, os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    run = api.get_run(repo, run_id)
    run_attempt = int(run.get("run_attempt") or 1)
    jobs = api.get_jobs(repo, run_id)
    failed_jobs = [job for job in jobs if str(job.get("conclusion") or "").lower() in FAILURE_CONCLUSIONS]

    assessments: list[JobAssessment] = []
    for job in failed_jobs:
        job_id = int(job.get("id") or 0)
        try:
            logs = api.get_job_logs(repo, job_id)
        except RuntimeError as exc:
            logs = f"Unable to fetch logs: {exc}"
        assessments.append(assess_job(job, logs))

    safe, reason = rerun_decision(assessments, run_attempt, max_attempts)
    rerun_triggered = False
    if safe and auto_rerun:
        api.rerun_failed_jobs(repo, run_id)
        rerun_triggered = True

    report = render_report(repo, run_id, run_attempt, assessments, safe, reason, rerun_triggered)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)
    else:
        print(report)

    prs = workflow_run.get("pull_requests") or []
    if comment_on_pr and prs:
        pr_number = prs[0].get("number")
        if pr_number:
            try:
                api.post_pr_comment(repo, int(pr_number), report)
            except RuntimeError as exc:
                print(f"::warning::Could not post PR comment: {exc}")

    _write_output("safe-to-rerun", "true" if safe else "false")
    _write_output("rerun-triggered", "true" if rerun_triggered else "false")
    _write_output("failed-jobs", str(len(assessments)))
    _write_output("wasted-minutes", f"{sum(a.duration_minutes for a in assessments):.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
