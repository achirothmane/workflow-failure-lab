from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from urllib.parse import quote

from ci_retry_gate import GitHubAPI
from flaky_test_intelligence import CaseObservation, FlakyTestSummary


@dataclass(frozen=True)
class OwnershipRule:
    test_pattern: str
    owners: tuple[str, ...]
    route: str = ""


@dataclass(frozen=True)
class CodeownersRule:
    pattern: str
    owners: tuple[str, ...]


@dataclass(frozen=True)
class OwnershipResolution:
    test_id: str
    owners: tuple[str, ...]
    source: str
    matched_pattern: str = ""
    source_file: str = ""
    route: str = ""

    @property
    def resolved(self) -> bool:
        return bool(self.owners)


def _normalize_owner(value: str) -> str:
    owner = value.strip()
    if not owner:
        raise ValueError("owner must be non-empty")
    if any(char.isspace() for char in owner):
        raise ValueError(f"owner must not contain whitespace: {owner!r}")
    return owner


def load_ownership_map(text: str) -> tuple[OwnershipRule, ...]:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("ownership map version must be 1")

    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list):
        raise ValueError("ownership map rules must be a list")

    rules: list[OwnershipRule] = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise ValueError("each ownership rule must be an object")

        pattern = str(raw.get("test_pattern") or "").strip()
        if not pattern:
            raise ValueError("ownership rule test_pattern must be non-empty")

        raw_owners = raw.get("owners")
        if not isinstance(raw_owners, list) or not raw_owners:
            raise ValueError(f"owners must be a non-empty list for pattern {pattern!r}")

        owners = tuple(_normalize_owner(str(item)) for item in raw_owners)
        if len(set(owners)) != len(owners):
            raise ValueError(f"duplicate owner in pattern {pattern!r}")

        route = str(raw.get("route") or "").strip()
        rules.append(
            OwnershipRule(
                test_pattern=pattern,
                owners=owners,
                route=route,
            )
        )
    return tuple(rules)


def parse_codeowners(text: str) -> tuple[CodeownersRule, ...]:
    rules: list[CodeownersRule] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        fields = line.split()
        if len(fields) < 2:
            continue

        pattern = fields[0].strip()
        if not pattern or pattern.startswith("!"):
            continue

        owners: list[str] = []
        invalid = False
        for raw_owner in fields[1:]:
            if raw_owner.startswith("#"):
                break
            try:
                owners.append(_normalize_owner(raw_owner))
            except ValueError:
                invalid = True
                break
        if invalid or not owners:
            continue

        rules.append(CodeownersRule(pattern=pattern, owners=tuple(owners)))
    return tuple(rules)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    result = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                while index + 1 < len(pattern) and pattern[index + 1] == "*":
                    index += 1
                if index + 1 < len(pattern) and pattern[index + 1] == "/":
                    index += 1
                    result.append("(?:.*/)?")
                else:
                    result.append(".*")
            else:
                result.append("[^/]*")
        elif char == "?":
            result.append("[^/]")
        else:
            result.append(re.escape(char))
        index += 1
    result.append("$")
    return re.compile("".join(result))


def codeowners_matches(pattern: str, source_file: str) -> bool:
    path = source_file.strip().replace("\\", "/").lstrip("./")
    raw = pattern.strip().replace("\\", "/")
    if not path or not raw:
        return False

    rooted = raw.startswith("/")
    normalized = raw.lstrip("/")
    if normalized.endswith("/"):
        normalized += "**"

    if "/" not in normalized:
        return any(
            bool(_glob_to_regex(normalized).match(part))
            for part in path.split("/")
        )

    if rooted:
        return bool(_glob_to_regex(normalized).match(path))

    return bool(_glob_to_regex(normalized).match(path))


def resolve_codeowners(
    source_file: str,
    rules: tuple[CodeownersRule, ...],
) -> tuple[tuple[str, ...], str]:
    owners: tuple[str, ...] = ()
    matched = ""
    for rule in rules:
        if codeowners_matches(rule.pattern, source_file):
            owners = rule.owners
            matched = rule.pattern
    return owners, matched


def _unique_source_file(
    test_id: str,
    observations: tuple[CaseObservation, ...],
) -> str:
    files = {
        item.source_file.strip().replace("\\", "/").lstrip("./")
        for item in observations
        if item.test_id == test_id and item.source_file.strip()
    }
    if len(files) == 1:
        return next(iter(files))
    return ""


def _resolve_mapping(
    test_id: str,
    rules: tuple[OwnershipRule, ...],
) -> OwnershipRule | None:
    matched: OwnershipRule | None = None
    for rule in rules:
        if fnmatchcase(test_id, rule.test_pattern):
            matched = rule
    return matched


def resolve_ownership(
    summaries: tuple[FlakyTestSummary, ...],
    observations: tuple[CaseObservation, ...],
    *,
    codeowners_rules: tuple[CodeownersRule, ...] = (),
    mapping_rules: tuple[OwnershipRule, ...] = (),
) -> dict[str, OwnershipResolution]:
    resolutions: dict[str, OwnershipResolution] = {}

    for summary in summaries:
        test_id = summary.test_id
        source_file = _unique_source_file(test_id, observations)

        if source_file and codeowners_rules:
            owners, pattern = resolve_codeowners(source_file, codeowners_rules)
            if owners:
                resolutions[test_id] = OwnershipResolution(
                    test_id=test_id,
                    owners=owners,
                    source="CODEOWNERS",
                    matched_pattern=pattern,
                    source_file=source_file,
                    route="CODEOWNERS",
                )
                continue

        mapped = _resolve_mapping(test_id, mapping_rules)
        if mapped is not None:
            resolutions[test_id] = OwnershipResolution(
                test_id=test_id,
                owners=mapped.owners,
                source="OWNERSHIP_MAP",
                matched_pattern=mapped.test_pattern,
                source_file=source_file,
                route=mapped.route or "ownership map",
            )
            continue

        resolutions[test_id] = OwnershipResolution(
            test_id=test_id,
            owners=(),
            source="UNRESOLVED",
            source_file=source_file,
        )

    return resolutions


def _decode_contents_payload(payload: object, path: str) -> str:
    if not isinstance(payload, dict):
        raise ValueError(f"{path} response was not a file")
    encoded = str(payload.get("content") or "").replace("\n", "")
    if not encoded:
        raise ValueError(f"{path} had no content")
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(f"{path} was not valid UTF-8 base64") from exc


def load_text_file_from_github(
    api: GitHubAPI,
    repo: str,
    ref: str,
    path: str,
) -> str | None:
    normalized = path.strip().lstrip("/")
    if not normalized:
        raise ValueError("repository path must be non-empty")
    if not ref.strip():
        raise ValueError("repository ref must be non-empty")

    encoded_path = quote(normalized, safe="/")
    encoded_ref = quote(ref, safe="")
    try:
        payload = api.request(
            "GET",
            f"/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}",
        )
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    return _decode_contents_payload(payload, normalized)


def load_codeowners_from_github(
    api: GitHubAPI,
    repo: str,
    ref: str,
) -> tuple[tuple[CodeownersRule, ...], str]:
    for path in (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        text = load_text_file_from_github(api, repo, ref, path)
        if text is not None:
            return parse_codeowners(text), path
    return (), ""


def load_ownership_map_from_github(
    api: GitHubAPI,
    repo: str,
    ref: str,
    path: str,
) -> tuple[OwnershipRule, ...]:
    text = load_text_file_from_github(api, repo, ref, path)
    if text is None:
        return ()
    return load_ownership_map(text)
