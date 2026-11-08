"""Structured validation issues shared by the loader, schema and rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    """One finding about a config, located by key path and (when known) line."""

    severity: Severity
    code: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "path": self.path,
            "line": self.line,
            "message": self.message,
        }

    def format(self) -> str:
        where = self.path or "<root>"
        if self.line is not None:
            where = f"{where} (line {self.line})"
        return f"{self.severity.value}: {where}: {self.message}"


def sort_issues(issues: Iterable[Issue]) -> list[Issue]:
    """Order issues deterministically: by line (unknown last), then path, then code."""
    return sorted(
        issues,
        key=lambda i: (i.line is None, i.line or 0, i.path, i.code, i.message),
    )


class ConfigError(Exception):
    """Raised when a config cannot be loaded or parsed. Carries every issue found."""

    def __init__(self, issues: Iterable[Issue]) -> None:
        self.issues: tuple[Issue, ...] = tuple(sort_issues(issues))
        super().__init__("\n".join(issue.format() for issue in self.issues))
