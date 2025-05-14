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

        # Local helper to cut duplication when instantiating the Scrapli driver.
        def _open_with_kwargs(**kwargs):
            """Instantiate and open a Scrapli driver with dynamic auth params.

            For devices that do *not* require login credentials (e.g. a Telnet
            connection to a console port) the inventory entry will leave
            ``username`` and ``password`` blank.  In that case we instruct
            Scrapli to *bypass* authentication altogether by setting
            ``auth_bypass=True`` instead of passing ``auth_username``/``auth_password``.
            """

            # Base connection settings (common for all devices).
            base_kwargs = dict(
                host=self._dev.host,
                auth_strict_key=False,
                timeout_socket=15,
                timeout_transport=15,
                timeout_ops=30,
            )

            # ----------------------------------------------------------------
            # Authentication selection
            # ----------------------------------------------------------------
            if self._dev.username is None and self._dev.password is None:
                # No credentials → skip interactive login.
                base_kwargs["auth_bypass"] = True
            else:
                # Normal username/password authentication.  (We intentionally
                # pass *even if* either value is an empty string – Scrapli will
                # raise during open() if the target refuses such credentials.)
                base_kwargs["auth_username"] = self._dev.username or ""
                base_kwargs["auth_password"] = self._dev.password or ""

            drv = drv_cls(
                **base_kwargs,
                **kwargs,
            )
            drv.open()
            return ScrapliConn(drv)

        # ------------------------------------------------------------------
        # 1. Determine which transport to try first.
        # ------------------------------------------------------------------
        # If *no* credentials are supplied we assume the target is a console
        # exposed over Telnet and therefore prioritise Telnet straight away.
        # Otherwise we keep the original behaviour of SSH-first with an
        # optional Telnet fallback (classic IOS only).

        no_auth = self._dev.username is None and self._dev.password is None

        # Helper function so we can attempt transports in the chosen order but
        # still share the common error-handling code.
        def _try_open(transport: str | None, port: int):
            kwargs = {"port": port}
            if transport:
                kwargs["transport"] = transport
            return _open_with_kwargs(**kwargs)

        # Build ordered list of (transport, port) attempts.
        attempts: list[tuple[str | None, int]] = []
        if no_auth:
            # Telnet first, maybe still try SSH if Telnet fails.
            attempts.append(("telnet", self._dev.port or 23))
            attempts.append((None, self._dev.port or 22))  # SSH default
        else:
            # Original flow: SSH then Telnet (IOS only).
            attempts.append((None, self._dev.port or 22))  # SSH default
            if self._dev.platform.lower() == "ios":
                attempts.append(("telnet", self._dev.port or 23))

        last_exc: Exception | None = None
        for transport, port in attempts:
            try:
                return _try_open(transport, port)
            except (ScrapliAuthenticationFailed, ScrapliTimeout) as exc:
                last_exc = exc
                # Continue to next attempt in list.

        # If we get here all attempts failed.
        raise RuntimeError(f"Connection attempts failed on {self._dev.host}: {last_exc}") from last_exc

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

