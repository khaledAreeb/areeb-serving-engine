import engine_bench


def test_package_exposes_installed_version() -> None:
    assert engine_bench.__version__ == "0.1.0"
