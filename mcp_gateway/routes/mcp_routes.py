"""FastAPI routes exposing the MCP interface.

Exposes two endpoints:
    * POST /mcp/run_command      – Execute a read‑only CLI command on a given device.
    * GET  /mcp/show_inventory   – Return the list of devices the caller is authorised to see.

Both endpoints rely on the auth guard defined in ``mcp_gateway.services.auth`` and delegate
real work to the ``executor`` and ``inventory_service`` service layers to keep I/O and
business logic outside the HTTP layer.
"""

from fastapi import APIRouter, Depends, HTTPException, status

# Pydantic models -------------------------------------------------------------
from mcp_gateway.models.mcp import (
    RunCommandRequest,
    RunCommandResponse,
    InventoryResponse,
)
from mcp_gateway.models.auth import User  # noqa: F401 – imported for type‑checking

# Service layer ----------------------------------------------------------------
from mcp_gateway.services import executor, inventory_service
from mcp_gateway.services.auth import get_current_user

router = APIRouter(prefix="", tags=["mcp"])


# ---------------------------------------------------------------------------
# /mcp/run_command
# ---------------------------------------------------------------------------

@router.post(
    "/run_command",
    response_model=RunCommandResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute a read‑only CLI command on a device",
    description="Runs the provided *show* command on the specified device and returns both raw and, if available, parsed output.",
)
async def run_command(
    req: RunCommandRequest, user: User = Depends(get_current_user)
) -> RunCommandResponse:
    """HTTP handler that proxies a run‑command MCP call to the executor service."""

    try:
        result: RunCommandResponse = await executor.run_command(
            device=req.device, command=req.command, user=user
        )
        return result

    except executor.DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except executor.CommandExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


# ---------------------------------------------------------------------------
# /mcp/show_inventory
# ---------------------------------------------------------------------------

@router.get(
    "/show_inventory",
    response_model=InventoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Return the list of accessible devices",
)
async def show_inventory(user: User = Depends(get_current_user)) -> InventoryResponse:
    """Return every device that *this* user may target.

    The inventory service performs the authorisation check so we do not leak
    devices that the caller is not entitled to view.
    """
    devices = inventory_service.list_devices(user=user)
    return InventoryResponse(devices=devices)


# ---------------------------------------------------------------------------
# Health check (optional)
# ---------------------------------------------------------------------------

@router.get("/ping", include_in_schema=False)
async def ping() -> dict[str, str]:
    """Simple liveness probe for load balancers and k8s probes."""
    return {"status": "ok"}

