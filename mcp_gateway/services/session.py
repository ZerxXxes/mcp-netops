"""Connection‑pool and session manager using **Scrapli**.

Scrapli gracefully falls back to keyboard‑interactive and handles most Cisco
variants without extra tweaks, so we switch from Netmiko to Scrapli to support
lab devices that disable the plain ``password`` auth method.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Dict

from fastapi.concurrency import run_in_threadpool
from loguru import logger
from scrapli.driver.core import IOSXEDriver, IOSXRDriver, NXOSDriver
from scrapli.exceptions import ScrapliAuthenticationFailed, ScrapliTimeout

from mcp_gateway.models.inventory import Device

# ---------------------------------------------------------------------------
# Driver map
# ---------------------------------------------------------------------------
_DRIVER_MAP = {
    "ios": IOSXEDriver,
    "iosxe": IOSXEDriver,
    "nxos": NXOSDriver,
    "iosxr": IOSXRDriver,
}

# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

_LOCK = threading.RLock()
_POOL: Dict[str, "ScrapliConn"] = {}


class ScrapliConn:  # thin wrapper for typing clarity
    def __init__(self, driver):
        self._driver = driver

    def is_alive(self):
        return self._driver.isalive()

    def send_command(self, command: str) -> str:
        return self._driver.send_command(command).result

    def close(self):
        self._driver.close()


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------

class _ConnectionContext(contextlib.AbstractAsyncContextManager):
    def __init__(self, dev_key: str, device: Device):
        self._key = dev_key
        self._dev = device
        self._conn: ScrapliConn | None = None

    async def __aenter__(self):  # type: ignore[override]
        global _POOL  # noqa: PLW0603
        with _LOCK:
            self._conn = _POOL.get(self._key)

        if self._conn is None or not self._conn.is_alive():
            logger.debug("Opening Scrapli SSH → %s", self._dev.hostname)
            self._conn = await run_in_threadpool(self._open)
            with _LOCK:
                _POOL[self._key] = self._conn
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):  # type: ignore[override]
        if exc_type:
            logger.warning("Closing bad session %s: %s", self._dev.hostname, exc)
            await run_in_threadpool(self._purge)
        return False

    # ------------------------------------------------------------------
    # Blocking helpers (thread‑pool)
    # ------------------------------------------------------------------

    def _open(self) -> ScrapliConn:
        drv_cls = _DRIVER_MAP.get(self._dev.platform.lower())
        if not drv_cls:
            raise RuntimeError(f"Unsupported platform for Scrapli: {self._dev.platform}")
        try:
            drv = drv_cls(
                host=self._dev.host,
                auth_username=self._dev.username,
                auth_password=self._dev.password,
                auth_strict_key=False,
                timeout_socket=15,
                timeout_transport=15,
                timeout_ops=30,
            )
            drv.open()
            return ScrapliConn(drv)
        except (ScrapliAuthenticationFailed, ScrapliTimeout) as exc:
            raise RuntimeError(f"SSH failure on {self._dev.host}: {exc}") from exc

    def _purge(self):
        global _POOL  # noqa: PLW0603
        if self._conn:
            with contextlib.suppress(Exception):
                self._conn.close()
        with _LOCK:
            _POOL.pop(self._key, None)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def get(device: Device):  # noqa: D401
    return _ConnectionContext(device.hostname, device)

