from __future__ import annotations

import re
from dataclasses import dataclass

from unknown_failure_intelligence import extract_unknown_evidence


CAUSE_NO_STABLE_ERROR_EVIDENCE = "NO_STABLE_ERROR_EVIDENCE"
CAUSE_AUTH_PERMISSION = "AUTH_PERMISSION"
CAUSE_GIT_VCS = "GIT_VCS"
CAUSE_COMMAND_CONFIG = "COMMAND_CONFIG"
CAUSE_TEST_BUILD = "TEST_BUILD"
CAUSE_PACKAGE_TOOL = "PACKAGE_TOOL"
CAUSE_TOOL_ACTION_SPECIFIC = "TOOL_ACTION_SPECIFIC"
CAUSE_AMBIGUOUS_OPERATIONAL = "AMBIGUOUS_OPERATIONAL"

CAUSE_ORDER = (
    CAUSE_NO_STABLE_ERROR_EVIDENCE,
    CAUSE_AUTH_PERMISSION,
    CAUSE_GIT_VCS,
    CAUSE_COMMAND_CONFIG,
    CAUSE_TEST_BUILD,
    CAUSE_PACKAGE_TOOL,
    CAUSE_TOOL_ACTION_SPECIFIC,
    CAUSE_AMBIGUOUS_OPERATIONAL,
)

_AUTH_RE = re.compile(
    r"\b(?:401|403|unauthori[sz]ed|forbidden|permission denied|access denied|"
    r"authentication failed|authorization failed|invalid credentials?|"
    r"insufficient permissions?|not permitted)\b",
    re.IGNORECASE,
)
_GIT_RE = re.compile(
    r"\b(?:git|non-fast-forward|refspec|merge conflict|conflict \(content\)|"
    r"failed to push some refs|could not read from remote repository|"
    r"repository not found|detached head|bad revision|ambiguous argument)\b",
    re.IGNORECASE,
)
_COMMAND_CONFIG_RE = re.compile(
    r"\b(?:command not found|not recognized as an internal or external command|"
    r"no such file or directory|unknown option|unrecognized (?:option|argument)|"
    r"invalid (?:option|argument|configuration|config)|missing required|"
    r"required (?:option|argument|value).*(?:missing|not provided)|"
    r"configuration error|config error|usage:)\b",
    re.IGNORECASE,
)
_TEST_BUILD_RE = re.compile(
    r"\b(?:test(?:s| suite)? (?:failed|failure)|failed tests?|build failed|"
    r"build failure|compilation error|compiler error|linker error|linking failed|"
    r"make(?:\[\d+\])?: \*\*\*|ninja: build stopped|cmake error|"
    r"pytest.*(?:failed|error)|jest.*(?:failed|error)|vitest.*(?:failed|error))\b",
    re.IGNORECASE,
)
_PACKAGE_TOOL_RE = re.compile(
    r"\b(?:npm|pnpm|yarn|pip|pipenv|poetry|uv|cargo|rustup|go mod|gem|bundler|"
    r"composer|gradle|maven|mvn|nuget|apt|apt-get|apk|brew)\b.*\b"
    r"(?:err(?:or)?|failed|failure|cannot|could not|unable)\b|"
    r"\b(?:err(?:or)?|failed|failure|cannot|could not|unable)\b.*\b"
    r"(?:npm|pnpm|yarn|pip|poetry|cargo|go mod|gradle|maven|nuget)\b",
    re.IGNORECASE,
)
_TOOL_ACTION_RE = re.compile(
    r"\b(?:docker|buildx|terraform|kubectl|helm|ansible|github|gh|"
    r"eslint|prettier|ruff|mypy|flake8|black|tox|bazel|buck|msbuild|"
    r"codecov|sonar|aws|azure|gcloud)\b.*\b"
    r"(?:error|failed|failure|fatal|panic|exception)\b|"
    r"\b(?:error|failed|failure|fatal|panic|exception)\b.*\b"
    r"(?:docker|terraform|kubectl|helm|eslint|ruff|mypy|bazel|msbuild|aws|gcloud)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UnknownCauseAssessment:
    cause: str
    evidence: tuple[str, ...]
    matched_evidence: tuple[str, ...] = ()


def _matching(evidence: tuple[str, ...], pattern: re.Pattern[str]) -> tuple[str, ...]:
    return tuple(line for line in evidence if pattern.search(line))[:3]


def decompose_unknown_cause(log_text: str) -> UnknownCauseAssessment:
    """Assign a diagnostic cause family to an UNKNOWN failure.

    This function never changes runtime classification and never authorizes a rerun.
    It only groups UNKNOWN failures for research and coverage analysis.
    """
    evidence = extract_unknown_evidence(log_text, limit=6)
    if not evidence:
        return UnknownCauseAssessment(
            CAUSE_NO_STABLE_ERROR_EVIDENCE,
            (),
            (),
        )

    for cause, pattern in (
        (CAUSE_AUTH_PERMISSION, _AUTH_RE),
        (CAUSE_GIT_VCS, _GIT_RE),
        (CAUSE_COMMAND_CONFIG, _COMMAND_CONFIG_RE),
        (CAUSE_TEST_BUILD, _TEST_BUILD_RE),
        (CAUSE_PACKAGE_TOOL, _PACKAGE_TOOL_RE),
        (CAUSE_TOOL_ACTION_SPECIFIC, _TOOL_ACTION_RE),
    ):
        matched = _matching(evidence, pattern)
        if matched:
            return UnknownCauseAssessment(cause, evidence[:3], matched)

    return UnknownCauseAssessment(
        CAUSE_AMBIGUOUS_OPERATIONAL,
        evidence[:3],
        evidence[:2],
    )
