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
        """Open a Scrapli connection with SSH *or* Telnet (IOS fallback).

        The primary transport for all devices remains SSH.  However, some Cisco
        IOS lab routers do not run an SSH server and can only be reached via
        Telnet on TCP/23.  For devices with ``platform == "ios"`` we therefore
        attempt a best-effort Telnet fallback if the initial SSH connection
        fails.

        Notes
        -----
        1. We *only* fall back to Telnet for classic IOS – all other platforms
           are expected to support SSH.
        2. The Telnet flow still re-uses the same Scrapli driver class; we just
           pass ``transport="telnet"`` so Scrapli instantiates the Telnet
           transport implementation.
        """

        def _open_with_kwargs(**kwargs):  # local helper to remove duplication
            drv = drv_cls(
                host=self._dev.host,
                auth_username=self._dev.username,
                auth_password=self._dev.password,
                auth_strict_key=False,
                timeout_socket=15,
                timeout_transport=15,
                timeout_ops=30,
                **kwargs,
            )
            drv.open()
            return ScrapliConn(drv)

        # ------------------------------------------------------------------
        # 1. Try the default SSH transport first.
        # ------------------------------------------------------------------
        try:
            return _open_with_kwargs()
        except (ScrapliAuthenticationFailed, ScrapliTimeout) as exc:
            # Only attempt Telnet fallback for classic IOS devices.
            if self._dev.platform.lower() != "ios":
                raise RuntimeError(f"SSH failure on {self._dev.host}: {exc}") from exc

            logger.debug("SSH failed for %s – attempting Telnet fallback", self._dev.hostname)

            try:
                return _open_with_kwargs(transport="telnet", port=23)
            except (ScrapliAuthenticationFailed, ScrapliTimeout) as tel_exc:
                raise RuntimeError(
                    f"SSH & Telnet failed on {self._dev.host}: {tel_exc}"
                ) from tel_exc

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

