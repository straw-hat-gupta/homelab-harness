"""homelab-harness control plane."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("homelab-harness")
except PackageNotFoundError:  # pragma: no cover - only when running from an unbuilt tree
    __version__ = "0.0.0+unknown"
