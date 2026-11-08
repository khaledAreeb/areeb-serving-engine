"""Canonical JSON and SHA-256 hashing for stable identifiers.

Every ID in engine-bench (deployment, series, cell, workload identity) is a
SHA-256 digest of a canonical JSON document. The canonical form:

* sorts object keys and uses compact separators (``,`` and ``:``);
* encodes as UTF-8 without ASCII escaping, and hashes strings exactly as given
  (no Unicode normalization);
* accepts only JSON-native values: ``dict`` with ``str`` keys, ``list``/``tuple``,
  ``str``, ``int``, ``bool``, finite ``float`` and ``None``. NaN, Infinity,
  non-string keys and any other type are rejected instead of silently coerced;
* normalizes ``-0.0`` to ``0.0``.

Identity digests wrap the payload in an envelope that carries the hash-scheme
version and the entity kind. Bumping ``HASH_SCHEME`` therefore invalidates
every old ID cleanly, and two entity kinds can never share an ID.

Pydantic models must be converted with ``model_dump(mode="json")`` first.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

HASH_SCHEME = 1
DISPLAY_PREFIX_LEN = 12

_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented in canonical JSON."""


def _normalize(value: Any, path: str) -> Any:
    # bool is checked before int because bool is a subclass of int.
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalizationError(f"non-finite float at {path}: {value!r}")
        return 0.0 if value == 0.0 else value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"non-string key at {path}: {key!r} ({type(key).__name__})"
                )
            normalized[key] = _normalize(item, f"{path}.{key}")
        return normalized
    if isinstance(value, list | tuple):
        return [_normalize(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise CanonicalizationError(f"unsupported type at {path}: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON text for ``value``."""
    return json.dumps(
        _normalize(value, "$"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_bytes(value: Any) -> bytes:
    """Return the canonical JSON encoding of ``value`` as UTF-8 bytes."""
    return canonical_json(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def identity_digest(kind: str, payload: Any) -> str:
    """Return the SHA-256 identity digest of ``payload`` for an entity ``kind``.

    The hashed document is ``{"hash_scheme": HASH_SCHEME, "kind": kind,
    "payload": payload}`` in canonical form.
    """
    if not kind:
        raise ValueError("kind must be a non-empty string")
    envelope = {"hash_scheme": HASH_SCHEME, "kind": kind, "payload": payload}
    return sha256_hex(canonical_bytes(envelope))


def display_id(digest: str) -> str:
    """Return the short display form (first 12 hex characters) of a full digest."""
    if not _HEX_DIGEST.fullmatch(digest):
        raise ValueError(f"not a lowercase 64-character hex SHA-256 digest: {digest!r}")
    return digest[:DISPLAY_PREFIX_LEN]
