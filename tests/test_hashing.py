"""Tests for canonical JSON and identity hashing.

Golden digests were computed independently: the expected canonical strings are
written out by hand below and were hashed with plain ``hashlib``, not with
``engine_bench.hashing``. A failure here means the hash scheme changed, which
would invalidate every stored ID. Bump ``HASH_SCHEME`` deliberately if so.
"""

import math
from typing import Any

import pytest

from engine_bench.hashing import (
    DISPLAY_PREFIX_LEN,
    HASH_SCHEME,
    CanonicalizationError,
    canonical_bytes,
    canonical_json,
    display_id,
    identity_digest,
    sha256_hex,
)

PLAIN = {"b": 1, "a": [1, 2.5, None, True]}
PLAIN_CANONICAL = '{"a":[1,2.5,null,true],"b":1}'
PLAIN_DIGEST = "d749551af46b4a5d105963e6fa3c8e0b889d422ca25c1c01ebbd97851eaf3280"

NON_ASCII = {"note": "ü", "model": "نموذج-Ω"}
NON_ASCII_CANONICAL = '{"model":"نموذج-Ω","note":"ü"}'
NON_ASCII_DIGEST = "be7d8d96e5a41cd891e207c39db2e964fa9b47e5899d4e84e66493001f077e8f"

CELL_IDENTITY_DIGEST = "605332c527c58c1f679f3fbfd12bd1731d5045c20244708a3573a8cb3936ebc9"


# --- canonical form -----------------------------------------------------------


def test_canonical_form_sorts_keys_and_uses_compact_separators() -> None:
    assert canonical_json(PLAIN) == PLAIN_CANONICAL


def test_key_order_does_not_change_the_canonical_form() -> None:
    a = {"x": {"b": 2, "a": 1}, "y": [{"d": 4, "c": 3}]}
    b = {"y": [{"c": 3, "d": 4}], "x": {"a": 1, "b": 2}}
    assert canonical_json(a) == canonical_json(b)
    assert identity_digest("series", a) == identity_digest("series", b)


def test_list_order_is_significant() -> None:
    assert canonical_json([1, 2]) != canonical_json([2, 1])


def test_tuples_are_encoded_like_lists() -> None:
    assert canonical_json({"grid": (1, 5, 10)}) == canonical_json({"grid": [1, 5, 10]})


def test_bool_and_int_stay_distinct() -> None:
    assert canonical_json([True, 1, False, 0]) == "[true,1,false,0]"


def test_negative_zero_is_normalized() -> None:
    assert canonical_json(-0.0) == canonical_json(0.0) == "0.0"


def test_int_and_float_are_not_conflated() -> None:
    assert canonical_json(1) != canonical_json(1.0)


# --- non-ASCII ------------------------------------------------------------------


def test_non_ascii_is_kept_verbatim_as_utf8() -> None:
    assert canonical_json(NON_ASCII) == NON_ASCII_CANONICAL
    assert canonical_bytes(NON_ASCII) == NON_ASCII_CANONICAL.encode("utf-8")
    assert "\\u" not in canonical_json(NON_ASCII)


def test_non_ascii_digest_is_stable() -> None:
    assert sha256_hex(canonical_bytes(NON_ASCII)) == NON_ASCII_DIGEST


# --- rejection ------------------------------------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_floats_are_rejected(bad: float) -> None:
    with pytest.raises(CanonicalizationError, match="non-finite"):
        canonical_json({"slo": {"ttft_ms": bad}})


def test_rejection_reports_the_path() -> None:
    with pytest.raises(CanonicalizationError, match=r"\$\.slo\.ttft_ms"):
        canonical_json({"slo": {"ttft_ms": math.nan}})


def test_non_string_keys_are_rejected() -> None:
    # json.dumps would silently turn 1 into "1" and collide with a real "1" key.
    with pytest.raises(CanonicalizationError, match="non-string key"):
        canonical_json({1: "a"})


@pytest.mark.parametrize("bad", [{1, 2}, b"bytes", object(), frozenset()])
def test_unsupported_types_are_rejected(bad: Any) -> None:
    with pytest.raises(CanonicalizationError, match="unsupported type"):
        canonical_json({"value": bad})


# --- digests ----------------------------------------------------------------------


def test_golden_plain_digest() -> None:
    assert sha256_hex(canonical_bytes(PLAIN)) == PLAIN_DIGEST


def test_golden_identity_digest_includes_scheme_and_kind() -> None:
    assert HASH_SCHEME == 1
    assert identity_digest("cell", PLAIN) == CELL_IDENTITY_DIGEST


def test_identity_digest_differs_from_bare_payload_digest() -> None:
    assert identity_digest("cell", PLAIN) != PLAIN_DIGEST


def test_entity_kinds_never_share_an_identity() -> None:
    assert identity_digest("cell", PLAIN) != identity_digest("deployment", PLAIN)


def test_identity_digest_requires_a_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        identity_digest("", PLAIN)


# --- display ids ------------------------------------------------------------------


def test_display_id_is_a_12_hex_prefix() -> None:
    assert DISPLAY_PREFIX_LEN == 12
    assert display_id(CELL_IDENTITY_DIGEST) == CELL_IDENTITY_DIGEST[:12]


@pytest.mark.parametrize("bad", ["abc", CELL_IDENTITY_DIGEST.upper(), CELL_IDENTITY_DIGEST + "0"])
def test_display_id_rejects_non_digests(bad: str) -> None:
    with pytest.raises(ValueError, match="digest"):
        display_id(bad)
