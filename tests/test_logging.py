import io
import json
from collections.abc import Iterator

import pytest
import structlog

from engine_bench.logging import configure_logging, get_logger


class _FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset_structlog() -> Iterator[None]:
    yield
    structlog.reset_defaults()


def test_non_tty_stream_gets_json_lines() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream)

    get_logger("planner").info("plan_built", cells=12)

    record = json.loads(stream.getvalue().strip())
    assert record["event"] == "plan_built"
    assert record["cells"] == 12
    assert record["component"] == "planner"
    assert record["level"] == "info"
    assert record["timestamp"].endswith("Z")


def test_tty_stream_gets_console_output() -> None:
    stream = _FakeTTY()
    configure_logging(stream=stream)

    get_logger().info("plan_built", cells=12)

    line = stream.getvalue().strip()
    assert "plan_built" in line
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)


def test_explicit_json_overrides_tty_detection() -> None:
    stream = _FakeTTY()
    configure_logging(stream=stream, json=True)

    get_logger().warning("placeholder_unresolved", key_path="model.id")

    assert json.loads(stream.getvalue())["level"] == "warning"


def test_level_filtering_drops_lower_levels() -> None:
    stream = io.StringIO()
    configure_logging(stream=stream, level="WARNING")

    log = get_logger()
    log.info("dropped")
    log.warning("kept")

    lines = stream.getvalue().strip().splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["kept"]


def test_unknown_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown log level"):
        configure_logging(stream=io.StringIO(), level="LOUD")
