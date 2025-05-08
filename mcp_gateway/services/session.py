"""Connection‑pool and session manager for south‑bound device access.

In this PoC we use **Netmiko** synchronously, but we still expose an *async*
interface so that upstream callers can `await session.get(...)` without blocking
the event loop.  We rely on FastAPI's built‑in thread pool via
``fastapi.concurrency.run_in_threadpool`` when we need to open a new SSH
connection.

Later you can swap this out for AsyncSSH or scrap the pool entirely and use
gNMI/RESTCONF – the caller contract stays the same.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Dict, Iterator

from fastapi.concurrency import run_in_threadpool
from loguru import logger
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

from mcp_gateway.models.inventory import Device

# ---------------------------------------------------------------------------
# Private state
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()
_POOL: Dict[str, ConnectHandler] = {}


# ---------------------------------------------------------------------------
# Context manager returned to callers
# ---------------------------------------------------------------------------

class _ConnectionContext(contextlib.AbstractAsyncContextManager):
    """Async context that yields a **connected** Netmiko session.

    Ensures that callers *await* the context but still reuse a blocking
    ``ConnectHandler`` under the hood.
    """

    def __init__(self, dev_key: str, device: Device):
        self._dev_key = dev_key
        self._device = device
        self._conn: ConnectHandler | None = None

    async def __aenter__(self) -> ConnectHandler:  # type: ignore[override]
        # Lazily open the connection in a thread so we don't block the event loop.
        global _POOL  # noqa: PLW0603
        with _LOCK:
            self._conn = _POOL.get(self._dev_key)

        if self._conn is None or not self._conn.is_alive():
            logger.debug("Opening new SSH session → %s (%s)", self._device.hostname, self._device.platform)
            self._conn = await run_in_threadpool(self._open_connection)
            with _LOCK:
                _POOL[self._dev_key] = self._conn
        else:
            logger.debug("Reusing cached SSH session → %s", self._device.hostname)

        return self._conn

    async def __aexit__(self, exc_type, exc, tb):  # type: ignore[override]
        # Do *not* close; keep alive for pool reuse.  Purge on errors.
        if exc_type is not None:
            logger.warning("Session error on %s: %s", self._device.hostname, exc)
            await run_in_threadpool(self._close_and_purge)
        return False  # propagate exceptions

    # ---------------------------------------------------------------------
    # Low‑level helpers (run in threadpool)
    # ---------------------------------------------------------------------

    def _open_connection(self) -> ConnectHandler:
        try:
            return ConnectHandler(
                device_type=self._device.netmiko_driver,
                host=self._device.host,
                username=self._device.username,
                password=self._device.password,
                fast_cli=True,
            )
        except (NetmikoTimeoutException, NetmikoAuthenticationException) as exc:
            raise RuntimeError(f"SSH failure on {self._device.host}: {exc}") from exc

    def _close_and_purge(self) -> None:
        global _POOL  # noqa: PLW0603
        if self._conn is not None:
            with contextlib.suppress(Exception):
                self._conn.disconnect()
        with _LOCK:
            _POOL.pop(self._dev_key, None)


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def get(device: Device) -> _ConnectionContext:  # noqa: D401
    """Return an *async* context manager that yields an active Netmiko session."""
    return _ConnectionContext(dev_key=device.hostname, device=device)

