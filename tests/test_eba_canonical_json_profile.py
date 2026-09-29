from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from eba_integration_contract import (
    CANONICAL_PROFILE_VERSION,
    ContractViolation,
    _parse_timestamp,
    canonical_json_bytes,
    strict_json_loads,
)

VECTORS = json.loads(
    (Path(__file__).parents[1] / "conformance" / "eba-canonical-json-v1.json").read_text(
        encoding="utf-8"
    )
)


def test_canonical_profile_is_versioned():
    assert VECTORS["profile"] == CANONICAL_PROFILE_VERSION


@pytest.mark.parametrize("case", VECTORS["accepted"], ids=lambda case: case["id"])
def test_accepted_vectors_have_exact_bytes_and_hash(case):
    body = canonical_json_bytes(case["value"])
    assert body == case["canonical_utf8"].encode("utf-8")
    assert hashlib.sha256(body).hexdigest() == case["sha256"]


def test_object_key_permutation_does_not_change_bytes():
    left = canonical_json_bytes({"z": 3, "a": 1, "m": 2})
    right = canonical_json_bytes({"m": 2, "z": 3, "a": 1})
    assert left == right == b'{"a":1,"m":2,"z":3}'


@pytest.mark.parametrize("case", VECTORS["rejected_raw"], ids=lambda case: case["id"])
def test_rejected_raw_vectors_fail_closed(case):
    with pytest.raises(ContractViolation, match=case["reason"]):
        strict_json_loads(case["raw"])


@pytest.mark.parametrize(
    "value,error",
    [
        ({"n": 1.5}, "CANONICAL_NON_INTEGER_NUMBER"),
        ({"n": 9007199254740992}, "CANONICAL_INTEGER_OUT_OF_RANGE"),
        ({1: "not-a-string-key"}, "CANONICAL_OBJECT_KEY_INVALID"),
    ],
)
def test_programmatic_unsupported_values_are_rejected(value, error):
    with pytest.raises(ContractViolation, match=error):
        canonical_json_bytes(value)


def test_lone_surrogate_is_rejected_programmatically():
    with pytest.raises(ContractViolation, match="CANONICAL_STRING_INVALID"):
        canonical_json_bytes({"s": chr(0xD800)})


def test_temporal_semantic_equivalence_is_not_byte_equivalence():
    case = VECTORS["semantic_not_byte_equivalence"][0]
    assert _parse_timestamp(case["a"], field="a") == _parse_timestamp(case["b"], field="b")
    assert canonical_json_bytes({"time": case["a"]}) != canonical_json_bytes({"time": case["b"]})
