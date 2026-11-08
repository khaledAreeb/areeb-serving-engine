"""engine-bench: reproducible LLM serving-engine benchmark."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("engine-bench")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
