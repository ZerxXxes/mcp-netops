"""Business‑logic layer that executes (read‑only) CLI commands on network devices.

This module is deliberately *framework‑free*: it contains no FastAPI imports so
it can be unit‑tested without an ASGI stack.
"""
from __future__ import annotations

import re
import functools
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from loguru import logger

from mcp_gateway.models.mcp import RunCommandResponse
from mcp_gateway.models.auth import User  # noqa: F401 – type‑checking only
from mcp_gateway.services import (
    inventory_service,
    session,
    parser,
    audit,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DeviceNotFoundError(RuntimeError):
    """Requested device does not exist in inventory or is not visible to caller."""


class CommandExecutionError(RuntimeError):
    """Raised when a CLI command fails or times out."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_READ_ONLY_PATTERN = re.compile(r"^(show|ping|traceroute)\b", re.IGNORECASE)


def _validate_command(command: str) -> None:
    """Reject commands that are not explicitly read‑only.

    *Very* blunt for the PoC: only allow commands that start with one of the
    approved keywords. Extend with an allow‑list file later.
    """
    if not _READ_ONLY_PATTERN.match(command.strip()):
        raise CommandExecutionError(
            "Only read‑only 'show', 'ping', or 'traceroute' commands are allowed in this PoC."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_command(device: str, command: str, user: User) -> RunCommandResponse:  # noqa: D401
    """Run *command* on *device* and return a :class:`RunCommandResponse`.

    Workflow:
        1. Authorise device against inventory.
        2. Verify command is read‑only.
        3. Get (or open) an SSH session from :pymod:`services.session`.
        4. Execute **blocking** Netmiko call inside FastAPI's thread‑pool helper.
        5. Optionally parse output via *parser* for structured JSON.
        6. Audit.
        7. Return the response DTO.
    """

    logger.debug("Run‑command requested: user=%s device=%s cmd=%s", user.username, device, command)

    # 1. Device lookup & RBAC --------------------------------------------------
    dev = inventory_service.get_device(device, for_user=user)
    if dev is None:
        raise DeviceNotFoundError(f"Unknown or unauthorised device: {device}")

    # 2. Command guard ---------------------------------------------------------
    _validate_command(command)

    # 3. Execute in session ----------------------------------------------------
    try:
        async with session.get(dev) as conn:
            # Netmiko is blocking; run it in FastAPI's threadpool wrapper.
            raw_output: str = await run_in_threadpool(
                functools.partial(conn.send_command, command, strip_prompt=False, strip_command=False)
            )
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Command failed: device=%s cmd=%s", device, command)
        raise CommandExecutionError(str(exc)) from exc

    # 4. Parse (best effort) ---------------------------------------------------
    parsed: Optional[dict[str, Any]] = None
    try:
        parsed = parser.maybe_parse(command=command, raw=raw_output, platform=dev.platform)
    except Exception:  # pylint: disable=broad-except
        logger.debug("Parser could not handle output for cmd=%s on %s", command, device)

    # 5. Audit -----------------------------------------------------------------
    audit.record(
        user=user.username,
        device=device,
        command=command,
        raw_output=raw_output,
        parsed=parsed,
    )

    return RunCommandResponse(stdout=raw_output, json=parsed)

