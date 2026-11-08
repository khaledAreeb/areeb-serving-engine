"""Structured logging for engine-bench.

* Logs go to stderr by default, so stdout stays reserved for machine-readable
  command output such as ``--json``.
* JSON lines are written when the stream is not a TTY (CI, files, pipes), and
  human-readable console lines when it is.
* Never pass dataset text (prompts, responses) into a log call. Log IDs, counts
  and hashes instead.
"""

from __future__ import annotations

import logging as _stdlib_logging
import sys
from typing import TextIO, cast

import structlog
from structlog.typing import FilteringBoundLogger, Processor


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except ValueError:  # closed stream
        return False


def _level_number(level: str) -> int:
    mapping = _stdlib_logging.getLevelNamesMapping()
    try:
        return mapping[level.upper()]
    except KeyError:
        raise ValueError(f"unknown log level: {level!r}") from None


def configure_logging(
    *,
    stream: TextIO | None = None,
    json: bool | None = None,
    level: str = "INFO",
) -> None:
    """Configure structlog for the whole process.

    ``json=None`` picks JSON when ``stream`` is not a TTY and console output when it is.
    """
    out = sys.stderr if stream is None else stream
    use_json = (not _is_tty(out)) if json is None else json

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if use_json:
        processors.append(structlog.processors.dict_tracebacks)
        processors.append(structlog.processors.JSONRenderer(sort_keys=True))
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=_is_tty(out)))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(_level_number(level)),
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Return a bound logger, optionally tagged with a component name."""
    logger = structlog.get_logger()
    if name is not None:
        logger = logger.bind(component=name)
    return cast(FilteringBoundLogger, logger)
