"""Command-line entry point for engine-bench.

Exit codes are mapped explicitly here rather than left to the CLI framework:

* 0 (``ExitCode.OK``): success.
* 1 (``ExitCode.INVALID``): the input was read but is invalid (for example a
  config with validation errors).
* 2 (``ExitCode.USAGE``): usage error, such as an unknown option or a missing file.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from enum import IntEnum

import typer
from typer.exceptions import TyperException

from engine_bench import __version__
from engine_bench.logging import configure_logging


class ExitCode(IntEnum):
    OK = 0
    INVALID = 1
    USAGE = 2


app = typer.Typer(
    name="engine-bench",
    help="Benchmark LLM serving engines and recommend one from measured evidence.",
    add_completion=False,
    no_args_is_help=False,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"engine-bench {__version__}")
        raise typer.Exit(int(ExitCode.OK))


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the engine-bench version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Benchmark LLM serving engines and recommend one from measured evidence."""
    configure_logging()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return an explicit exit code instead of calling ``sys.exit``.

    Typer 0.2x vendors click privately, so only Typer's public exception types are
    used here. Every framework-level error (unknown option, bad or missing
    parameter) derives from ``TyperException`` and is a usage error.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        result = app(args=args, prog_name="engine-bench", standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except typer.Abort:
        typer.echo("Aborted.", err=True)
        return int(ExitCode.USAGE)
    except TyperException as exc:
        show = getattr(exc, "show", None)
        if callable(show):
            show()
        else:
            typer.echo(f"Error: {exc}", err=True)
        return int(ExitCode.USAGE)
    if isinstance(result, int):
        return result
    return int(ExitCode.OK)


def run() -> None:
    """Console-script entry point."""
    sys.exit(main())
