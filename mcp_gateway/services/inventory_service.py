"""Inventory loader + RBAC filter.

Reads ``inventory/inventory.yaml`` on first access (with naïve mtime caching)
and provides helper functions for other services.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from loguru import logger
from pydantic import ValidationError

from mcp_gateway.config import settings  # type: ignore
from mcp_gateway.models.inventory import Device, DevicePublic
from mcp_gateway.models.auth import User  # noqa: F401 – for type hints

# ---------------------------------------------------------------------------
# Constants / cache state
# ---------------------------------------------------------------------------

_INVENTORY_PATH = Path(settings.INVENTORY_FILE).resolve()

_CACHE: Dict[str, Device] = {}
_CACHE_MTIME: float = 0.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InventoryLoadError(RuntimeError):
    """Raised when the YAML cannot be parsed or validated."""


# ---------------------------------------------------------------------------
# File loader
# ---------------------------------------------------------------------------


def _load_yaml() -> Dict[str, Device]:
    """(Re)load YAML file, return mapping hostname → Device."""
    global _CACHE_MTIME  # noqa: PLW0603

    try:
        mtime = _INVENTORY_PATH.stat().st_mtime
    except FileNotFoundError as exc:
        raise InventoryLoadError(f"Inventory file missing: {_INVENTORY_PATH}") from exc

    if mtime <= _CACHE_MTIME and _CACHE:
        return _CACHE  # still fresh

    logger.debug("Reloading inventory from %s", _INVENTORY_PATH)
    try:
        raw = yaml.safe_load(_INVENTORY_PATH.read_text()) or {}
    except yaml.YAMLError as exc:
        raise InventoryLoadError(f"YAML syntax error in {_INVENTORY_PATH}: {exc}") from exc

    inventory: Dict[str, Device] = {}
    for host_entry in raw.get("devices", []):
        try:
            dev = Device.model_validate(host_entry)
        except ValidationError as exc:
            raise InventoryLoadError(f"Invalid device entry in inventory: {exc}") from exc
        inventory[dev.hostname] = dev

    # cache swap
    _CACHE.clear(); _CACHE.update(inventory)  # noqa: E702 – single‑line ok here
    _CACHE_MTIME = mtime
    return _CACHE


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_device(hostname: str, *, for_user: User) -> Optional[Device]:  # noqa: D401
    """Return **Device** if visible to *user* else ``None``."""
    inventory = _load_yaml()
    dev = inventory.get(hostname)
    if dev is None:
        return None

    return dev if _is_authorised(dev, for_user) else None


def list_devices(*, user: User) -> List[DevicePublic]:  # noqa: D401
    """Return public view (no passwords) of devices allowed for *user*."""
    inventory = _load_yaml()
    return [DevicePublic(**d.model_dump()) for d in inventory.values() if _is_authorised(d, user)]


# ---------------------------------------------------------------------------
# RBAC guard – very naive PoC
# ---------------------------------------------------------------------------


def _is_authorised(device: Device, user: User) -> bool:
    """Allow if user.role == 'admin' or tag intersection."""
    if "admin" in user.roles:
        return True
    return bool(set(device.tags) & set(user.allowed_tags))

