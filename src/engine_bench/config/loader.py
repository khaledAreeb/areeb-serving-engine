"""Load experiment YAML into plain Python data plus a key-path -> line map.

Uses the ruamel.yaml round-trip loader because it:

* rejects duplicate keys at every nesting level (PyYAML silently keeps the last);
* keeps line numbers for error messages.

The loader returns only JSON-native data (dict with str keys, list, str, int,
float, bool, None). Any explicit YAML tag (``!!python/...``, ``!!str``, custom
``!tags``) is rejected: the round-trip loader never executes them, but it
silently drops some tags, which would hide intent. Dates and timestamps are
rejected too, so values such as revisions are never reinterpreted.

Key paths use dots for mapping keys and brackets for list items, for example
``engines[1].image`` or ``slo.per_request.ttft_ms``. Lines are 1-based.
"""

from __future__ import annotations

import datetime as _dt
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq, TaggedScalar
from ruamel.yaml.constructor import DuplicateKeyError
from ruamel.yaml.error import MarkedYAMLError
from ruamel.yaml.scalarbool import ScalarBoolean

from engine_bench.config.issues import ConfigError, Issue, Severity

_DUPLICATE_KEY = re.compile(r'found duplicate key "(?P<key>.*?)"')
_LAST_SEGMENT = re.compile(r"(?:^|\.)([^.\[\]]+)$")


def join_key(parent: str, key: str) -> str:
    return f"{parent}.{key}" if parent else key


def join_index(parent: str, index: int) -> str:
    return f"{parent}[{index}]"


def parent_path(path: str) -> str | None:
    """Return the parent key path, or None for the root."""
    if not path:
        return None
    if path.endswith("]"):
        return path[: path.rindex("[")]
    if "." in path:
        return path[: path.rindex(".")]
    return ""


@dataclass(frozen=True)
class LoadedYaml:
    data: dict[str, Any]
    lines: Mapping[str, int] = field(default_factory=dict)
    source: str = "<string>"

    def line_for(self, path: str) -> int | None:
        """Line of ``path``, or of its nearest ancestor that has one."""
        current: str | None = path
        while current is not None:
            line = self.lines.get(current)
            if line is not None:
                return line
            current = parent_path(current)
        return None


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.allow_duplicate_keys = False
    return yaml


def _node_tag(node: Any) -> str | None:
    tag = getattr(node, "tag", None)
    value = getattr(tag, "value", None)
    return value if isinstance(value, str) else None


class _Converter:
    def __init__(self) -> None:
        self.lines: dict[str, int] = {}
        self.issues: list[Issue] = []

    def _error(self, code: str, path: str, message: str) -> None:
        line = self.lines.get(path)
        self.issues.append(Issue(Severity.ERROR, code, path, message, line))

    def convert(self, node: Any, path: str) -> Any:
        if isinstance(node, TaggedScalar):
            self._error("yaml_tag", path, f"YAML tags are not allowed (found {_node_tag(node)})")
            return None
        if isinstance(node, CommentedMap):
            tag = _node_tag(node)
            if tag is not None:
                self._error("yaml_tag", path, f"YAML tags are not allowed (found {tag})")
                return None
            return self._mapping(node, path)
        if isinstance(node, CommentedSeq):
            tag = _node_tag(node)
            if tag is not None:
                self._error("yaml_tag", path, f"YAML tags are not allowed (found {tag})")
                return None
            return self._sequence(node, path)
        return self._scalar(node, path)

    def _mapping(self, node: CommentedMap, path: str) -> dict[str, Any] | None:
        result: dict[str, Any] = {}
        ok = True
        for key in node:
            if not isinstance(key, str):
                line = node.lc.key(key)[0] + 1
                self.issues.append(
                    Issue(
                        Severity.ERROR,
                        "non_string_key",
                        path,
                        f"mapping keys must be strings (found {type(key).__name__} {key!r})",
                        line,
                    )
                )
                ok = False
                continue
            child = join_key(path, str(key))
            self.lines[child] = node.lc.key(key)[0] + 1
            result[str(key)] = self.convert(node[key], child)
        return result if ok else None

    def _sequence(self, node: CommentedSeq, path: str) -> list[Any]:
        items: list[Any] = []
        for index, item in enumerate(node):
            child = join_index(path, index)
            self.lines[child] = node.lc.item(index)[0] + 1
            items.append(self.convert(item, child))
        return items

    def _scalar(self, node: Any, path: str) -> Any:
        if node is None or type(node) is bool:
            return node
        if isinstance(node, _dt.date | _dt.datetime):
            self._error(
                "unsupported_value",
                path,
                "dates and timestamps are not supported; quote the value to keep it as text",
            )
            return None
        if isinstance(node, ScalarBoolean):  # anchored booleans; an int subclass
            return bool(node)
        if isinstance(node, int):
            return int(node)
        if isinstance(node, float):
            return float(node)
        if isinstance(node, str):
            return str(node)
        self._error("unsupported_value", path, f"unsupported YAML value type {type(node).__name__}")
        return None


def _duplicate_key_issue(exc: DuplicateKeyError, text: str) -> Issue:
    problem = exc.problem or ""
    match = _DUPLICATE_KEY.search(problem)
    key = match.group("key") if match else None
    line = exc.problem_mark.line + 1 if exc.problem_mark is not None else None
    path = key or ""
    if key is not None:
        # Re-parse with duplicates allowed to recover the key's full path.
        relaxed = YAML(typ="rt")
        relaxed.allow_duplicate_keys = True
        try:
            converter = _Converter()
            converter.convert(relaxed.load(io.StringIO(text)), "")
            candidates = [
                p for p in converter.lines if (m := _LAST_SEGMENT.search(p)) and m.group(1) == key
            ]
            if len(candidates) == 1:
                path = candidates[0]
        except MarkedYAMLError:
            pass
    name = f"'{key}'" if key is not None else "a key"
    return Issue(Severity.ERROR, "duplicate_key", path, f"duplicate key {name}", line)


def load_yaml_text(text: str, *, source: str = "<string>") -> LoadedYaml:
    """Parse YAML text. Raises ConfigError listing every problem found."""
    try:
        document = _yaml().load(io.StringIO(text))
    except DuplicateKeyError as exc:
        raise ConfigError([_duplicate_key_issue(exc, text)]) from None
    except MarkedYAMLError as exc:
        line = exc.problem_mark.line + 1 if exc.problem_mark is not None else None
        message = f"YAML syntax error: {exc.problem or exc.context or 'invalid YAML'}"
        raise ConfigError([Issue(Severity.ERROR, "yaml_syntax", "", message, line)]) from None

    if document is None:
        raise ConfigError([Issue(Severity.ERROR, "empty_config", "", "the config is empty", None)])
    if not isinstance(document, CommentedMap):
        raise ConfigError(
            [Issue(Severity.ERROR, "invalid_root", "", "the config root must be a mapping", 1)]
        )

    converter = _Converter()
    data = converter.convert(document, "")
    if converter.issues or not isinstance(data, dict):
        raise ConfigError(converter.issues)
    return LoadedYaml(data=data, lines=dict(converter.lines), source=source)


def load_yaml_file(path: Path) -> LoadedYaml:
    """Read and parse a YAML file.

    Missing or unreadable files raise ``OSError`` (a usage error for the CLI);
    invalid content raises ``ConfigError``.
    """
    text = path.read_text(encoding="utf-8")
    return load_yaml_text(text, source=str(path))
