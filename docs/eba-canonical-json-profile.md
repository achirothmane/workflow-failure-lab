# EBA canonical JSON profile v1

Profile: `eba.canonical-json/v1`  
Artifact contract: `eba.integration/v0.1`

This profile defines the byte representation used when an EBA artifact is
hashed, referenced, or integrity-bound across Python and Go owners. It is a
bounded compatibility profile, not a universal JSON ontology.

## Supported domain

- root value: JSON object;
- object keys: unique strings;
- values: object, array, string, boolean, null, or integer;
- integers: inclusive range `[-9007199254740991, 9007199254740991]`;
- strings: Unicode scalar values;
- floats, exponent-form numbers, negative zero, duplicate keys, malformed
  Unicode and unsupported programmatic types: rejected.

Objects are serialized with keys in lexical order and no insignificant
whitespace.

String escaping follows the byte form emitted by Go `encoding/json` for the
supported domain:

- quote, backslash and control characters are escaped as required by JSON;
- `<`, `>` and `&` use `\u003c`, `\u003e` and `\u0026`;
- U+2028 and U+2029 use `\u2028` and `\u2029`;
- other supported Unicode is emitted directly as UTF-8.

The accepted and rejected reference corpus is
`conformance/eba-canonical-json-v1.json`.

## Semantic equality is not byte rewriting

Canonical JSON does not normalize domain strings. In particular,
`2026-09-28T12:00:00Z` and `2026-09-28T14:00:00+02:00` are different
JSON strings and therefore different canonical bytes. The temporal profile can
still treat them as the same instant after parsing.

Likewise, arrays remain ordered. A domain that treats a collection as a set
must sort it before canonical serialization or define the ordering in its own
profile. Canonical JSON does not guess semantic set equality.

## Ingestion rule

External raw EBA JSON must pass strict parsing before it can contribute to an
authorizing hash or reference. A parser path that silently keeps the last
duplicate key, rounds a large number, or converts a fractional number into an
integer is not conformant.

Internally constructed Python artifacts use the same bounded canonical encoder.
Aegis parses external EBA artifacts through the strict Go decoder before
integrity and signed-reference checks.

## Migration

New authorizing artifacts carry `canonical_profile =
"eba.canonical-json/v1"`. Historical artifacts remain readable as history but
are not silently upgraded to the new cross-language byte guarantee.

A security-invalid legacy representation must be regenerated under the current
profile before it can authorize an effect.

## Scope exclusions

Genesis/bootstrap canonicalization remains owned by its existing assurance
contract and is not changed by this profile.

The current EASL repository does not publish a promised canonical serialized
artifact/hash format. Its deterministic evaluation semantics remain in scope,
but C05 does not invent a new EASL byte contract merely to make every repository
look identical.
