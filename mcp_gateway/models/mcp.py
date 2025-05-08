"""Pydantic DTOs describing the MCP north‑bound contract.

These are the *payload* objects used by ``routes/mcp_routes.py``.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from mcp_gateway.models.inventory import DevicePublic

# ---------------------------------------------------------------------------
# Run‑command
# ---------------------------------------------------------------------------


class RunCommandRequest(BaseModel):
    """Request body for **POST /mcp/run_command**."""

    device: str = Field(..., description="Logical hostname as defined in inventory.yaml")
    command: str = Field(..., description="Read‑only CLI command, e.g. 'show ip int brief'")

    model_config = {"extra": "forbid"}


class RunCommandResponse(BaseModel):
    """Return payload for *run_command* call."""

    stdout: str = Field(..., description="Raw CLI text output")
    json: Optional[dict[str, Any]] = Field(
        default=None,
        description="Structured parse of *stdout* using pyATS Genie when available.",
    )

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# Inventory listing
# ---------------------------------------------------------------------------


class InventoryResponse(BaseModel):
    """Return all accessible devices (public view)."""

    devices: list[DevicePublic]

    model_config = {"extra": "forbid"}

