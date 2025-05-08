"""Package root for *mcp_gateway*.

Re‑exports the FastAPI ``app`` so you can run::

    uvicorn mcp_gateway:app

from anywhere on PYTHONPATH.
"""
from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("mcp_gateway")  # Works when installed via pip/poetry
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.1.0"

# Export app for Uvicorn convenience --------------------------------------------------
from mcp_gateway.main import app  # noqa: E402  pylint: disable=wrong-import-position

__all__ = ["app", "__version__"]

