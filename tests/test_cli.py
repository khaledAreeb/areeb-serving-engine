import pytest

from engine_bench import __version__
from engine_bench.cli import ExitCode, main


def test_exit_code_values_are_fixed() -> None:
    assert (ExitCode.OK, ExitCode.INVALID, ExitCode.USAGE) == (0, 1, 2)


def test_unknown_option_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--no-such-option"]) == ExitCode.USAGE
    assert "No such option" in capsys.readouterr().err


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["no-such-command"]) == ExitCode.USAGE
    assert "No such command" in capsys.readouterr().err


def test_help_exits_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == ExitCode.OK
    assert "Usage" in capsys.readouterr().out


def test_version_exits_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == ExitCode.OK
    assert capsys.readouterr().out.strip() == f"engine-bench {__version__}"
