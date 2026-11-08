"""Named placeholders for undecided values, and the field types that accept them.

Each pinnable field accepts a real value or exactly one named placeholder: its
own. Every other known placeholder is rejected in that field, so ``GPU_SYSTEM``
can never be mistaken for a model ID or a revision.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator


class Placeholder(StrEnum):
    MODEL_ID = "EXACT_MODEL_ID"
    COMMIT = "EXACT_COMMIT"
    DATASET_COMMIT = "EXACT_DATASET_COMMIT"
    GPU_SYSTEM = "GPU_SYSTEM"
    GPU_UUID = "GPU_UUID"
    IMAGE_DIGEST = "EXACT_IMAGE_DIGEST"
    AIPERF_VERSION = "EXACT_AIPERF_VERSION"


KNOWN_PLACEHOLDERS = frozenset(p.value for p in Placeholder)

_COMMIT = re.compile(r"[0-9a-f]{40}")
_IMAGE = re.compile(r"(?P<repo>[^@\s]+)@(?P<digest>[^@\s]+)")
_SHA256_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_VERSION = re.compile(
    r"\d+(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(\+[0-9a-z]+(\.[0-9a-z]+)*)?"
)


def _reject_foreign_placeholder(value: str, own: Placeholder) -> None:
    if value in KNOWN_PLACEHOLDERS and value != own.value:
        raise ValueError(
            f"placeholder {value} is not valid here; this field accepts only {own.value} "
            "as a placeholder"
        )


def _text(own: Placeholder) -> Callable[[str], str]:
    def check(value: str) -> str:
        if not value or value != value.strip() or any(c.isspace() for c in value):
            raise ValueError("must be a non-empty value without whitespace")
        _reject_foreign_placeholder(value, own)
        return value

    return check


def _revision(own: Placeholder) -> Callable[[str], str]:
    def check(value: str) -> str:
        if value == own.value or _COMMIT.fullmatch(value):
            return value
        _reject_foreign_placeholder(value, own)
        raise ValueError(
            "revisions must be full 40-character lowercase commit hashes "
            f"(or {own.value}); got {value!r}"
        )

    return check


def _image(value: str) -> str:
    match = _IMAGE.fullmatch(value)
    if match is None:
        if value in KNOWN_PLACEHOLDERS:
            raise ValueError(
                f"placeholder {value} is not valid here; use <repository>@"
                f"{Placeholder.IMAGE_DIGEST.value} until the digest is pinned"
            )
        raise ValueError(
            "images must be pinned by digest: <repository>@sha256:<64 hex> "
            f"(or <repository>@{Placeholder.IMAGE_DIGEST.value}); got {value!r}"
        )
    digest = match.group("digest")
    if digest == Placeholder.IMAGE_DIGEST.value or _SHA256_DIGEST.fullmatch(digest):
        return value
    _reject_foreign_placeholder(digest, Placeholder.IMAGE_DIGEST)
    raise ValueError(
        "image digests must be sha256:<64 lowercase hex> "
        f"(or {Placeholder.IMAGE_DIGEST.value}); got {digest!r}"
    )


def _aiperf_version(value: str) -> str:
    if value == Placeholder.AIPERF_VERSION.value or _VERSION.fullmatch(value):
        return value
    _reject_foreign_placeholder(value, Placeholder.AIPERF_VERSION)
    raise ValueError(
        "must be an exact version such as 1.2.3 "
        f"(or {Placeholder.AIPERF_VERSION.value}); got {value!r}"
    )


ModelId = Annotated[str, AfterValidator(_text(Placeholder.MODEL_ID))]
ModelRevision = Annotated[str, AfterValidator(_revision(Placeholder.COMMIT))]
DatasetRevision = Annotated[str, AfterValidator(_revision(Placeholder.DATASET_COMMIT))]
GpuSystem = Annotated[str, AfterValidator(_text(Placeholder.GPU_SYSTEM))]
GpuUuid = Annotated[str, AfterValidator(_text(Placeholder.GPU_UUID))]
ImageRef = Annotated[str, AfterValidator(_image)]
AiperfVersion = Annotated[str, AfterValidator(_aiperf_version)]


def placeholder_in(value: str) -> Placeholder | None:
    """Return the placeholder a field value uses, if any (including image references)."""
    if value in KNOWN_PLACEHOLDERS:
        return Placeholder(value)
    match = _IMAGE.fullmatch(value)
    if match is not None and match.group("digest") == Placeholder.IMAGE_DIGEST.value:
        return Placeholder.IMAGE_DIGEST
    return None
