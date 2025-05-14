"""Pydantic data models for device inventory entries.

The *internal* ``Device`` model keeps authentication secrets so that service
layers can open SSH sessions.  The *public* ``DevicePublic`` variant omits any
credential fields so it is safe to serialise in API responses.
"""
from __future__ import annotations

from typing import ClassVar, Mapping

from pydantic import BaseModel, Field, computed_field, model_validator


class Device(BaseModel):
    """Complete view of a network device row in *inventory.yaml*."""

    hostname: str = Field(..., description="Logical name used in MCP calls")
    host: str = Field(..., description="DNS name or management IP")
    platform: str = Field(..., description="ios, iosxe, nxos, etc.")
    username: str
    password: str  # noqa: S105 – secrets are kept in‑memory only for session auth
    tags: list[str] = Field(default_factory=list, description="Arbitrary RBAC tags")

    # Optional TCP port override for the management protocol.  If *None* the
    # connection logic picks sensible defaults based on the transport
    # (22 for SSH, 23 for Telnet).
    port: int | None = Field(
        default=None,
        ge=1,
        le=65535,
        description="Custom TCP port for SSH/Telnet (optional)",
    )

    # ---------------------------------------------------------------------
    # Netmiko driver mapping
    # ---------------------------------------------------------------------

    _NETMIKO_MAP: ClassVar[Mapping[str, str]] = {
        "ios": "cisco_ios",
        "iosxe": "cisco_ios",
        "iosxr": "cisco_xr",
        "nxos": "cisco_nxos",
        "asa": "cisco_asa",
    }

    @computed_field  # type: ignore[misc]
    @property
    def netmiko_driver(self) -> str:  # noqa: D401
        """Return Netmiko *device_type* string for this platform."""
        try:
            return self._NETMIKO_MAP[self.platform.lower()]
        except KeyError as exc:  # pragma: no cover – caught by validation
            raise ValueError(f"Unsupported platform: {self.platform}") from exc

    # ------------------------------------------------------------------
    # Pydantic config
    # ------------------------------------------------------------------

    model_config = {
        "extra": "forbid",
        "frozen": True,
        "repr_exclude": {"password"},
    }

    # Validate platform at load‑time (for early failure)
    @model_validator(mode="after")
    def _check_platform(self):  # noqa: D401
        self.netmiko_driver  # triggers ValueError if unsupported
        return self


class DevicePublic(BaseModel):
    """Subset of :class:`Device` safe for API responses (no secrets)."""

    hostname: str
    host: str
    platform: str
    tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "ignore", "frozen": True}

