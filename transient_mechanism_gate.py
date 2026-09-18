from __future__ import annotations

import re
from dataclasses import dataclass


MECHANISM_TRANSIENT_SUPPORTED = "TRANSIENT_MECHANISM_SUPPORTED"
MECHANISM_DETERMINISTIC = "DETERMINISTIC_MECHANISM"
MECHANISM_UNPROVEN = "TRANSIENT_MECHANISM_UNPROVEN"

REASON_TIMEOUT = "TIMEOUT"
REASON_CONNECTION_RESET = "CONNECTION_RESET"
REASON_DNS_RESOLUTION = "DNS_RESOLUTION"
REASON_SERVER_5XX = "SERVER_5XX"
REASON_RATE_LIMIT = "RATE_LIMIT"
REASON_TEMPORARY_UNAVAILABLE = "TEMPORARY_UNAVAILABLE"
REASON_NETWORK_EOF = "NETWORK_EOF"
REASON_AUTH_PERMISSION = "AUTH_PERMISSION"
REASON_COMMAND_CONFIG = "COMMAND_CONFIG"
REASON_TEST_BUILD = "TEST_BUILD"
REASON_GIT_STATE = "GIT_VCS_STATE"
REASON_NO_TRANSIENT_MECHANISM = "NO_TRANSIENT_MECHANISM_EVIDENCE"

_TRANSIENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        REASON_TIMEOUT,
        re.compile(
            r"\b(?:timed?\s*out|timeout|etimedout|deadline exceeded)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_CONNECTION_RESET,
        re.compile(
            r"\b(?:connection reset|econnreset|connection refused|econnrefused|"
            r"broken pipe|connection aborted)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_DNS_RESOLUTION,
        re.compile(
            r"\b(?:could not resolve|temporary failure in name resolution|"
            r"name or service not known|enotfound|eai_again|dns)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_SERVER_5XX,
        re.compile(
            r"\b(?:http\s*)?(?:500|502|503|504)\b|\bserver error\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_RATE_LIMIT,
        re.compile(
            r"\b(?:429|rate limit(?:ed)?|too many requests)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_TEMPORARY_UNAVAILABLE,
        re.compile(
            r"\b(?:temporar(?:y|ily) unavailable|service unavailable|"
            r"try again later|transient failure)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REASON_NETWORK_EOF,
        re.compile(
            r"\b(?:unexpected eof|read: eof|network.*eof|tls handshake timeout)\b",
            re.IGNORECASE,
        ),
    ),
)

_DETERMINISTIC_CAUSES = {
    "AUTH_PERMISSION": REASON_AUTH_PERMISSION,
    "COMMAND_CONFIG": REASON_COMMAND_CONFIG,
    "TEST_BUILD": REASON_TEST_BUILD,
    "GIT_VCS": REASON_GIT_STATE,
}


@dataclass(frozen=True)
class TransientMechanismAssessment:
    status: str
    reasons: tuple[str, ...]
    transient_evidence: tuple[str, ...] = ()
    deterministic_causes: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return self.status == MECHANISM_TRANSIENT_SUPPORTED


def assess_transient_mechanism(
    signature: str,
    causes: tuple[str, ...] = (),
) -> TransientMechanismAssessment:
    """Require independent evidence of a transient failure mechanism.

    Cause-family labels alone never prove transience. Explicit transient mechanism
    evidence may override a deterministic-looking diagnostic family because the
    signature then provides stronger, direct evidence about the failure mechanism.
    """
    text = (signature or "").strip()
    transient_reasons: list[str] = []
    transient_evidence: list[str] = []

    for reason, pattern in _TRANSIENT_PATTERNS:
        match = pattern.search(text)
        if match:
            transient_reasons.append(reason)
            transient_evidence.append(match.group(0))

    if transient_reasons:
        return TransientMechanismAssessment(
            MECHANISM_TRANSIENT_SUPPORTED,
            reasons=tuple(dict.fromkeys(transient_reasons)),
            transient_evidence=tuple(dict.fromkeys(transient_evidence)),
            deterministic_causes=tuple(
                cause for cause in causes if cause in _DETERMINISTIC_CAUSES
            ),
        )

    deterministic = tuple(
        cause for cause in causes if cause in _DETERMINISTIC_CAUSES
    )
    if deterministic:
        reasons = tuple(
            dict.fromkeys(_DETERMINISTIC_CAUSES[cause] for cause in deterministic)
        )
        return TransientMechanismAssessment(
            MECHANISM_DETERMINISTIC,
            reasons=reasons,
            deterministic_causes=deterministic,
        )

    return TransientMechanismAssessment(
        MECHANISM_UNPROVEN,
        reasons=(REASON_NO_TRANSIENT_MECHANISM,),
    )
