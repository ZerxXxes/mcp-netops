"""Central configuration object (env‑driven).

Uses Pydantic *BaseSettings* so everything can be overridden via environment
variables or a local *.env* file.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """Load settings from env vars or .env."""

    INVENTORY_FILE: str = Field(
        default="mcp_gateway/inventory/inventory.yaml",
        description="Path to YAML inventory file",
    )

    JWT_SECRET: str = Field(
        default="dev‑secret‑change‑me",
        description="HS256 secret for PoC tokens (replace in prod!)",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf‑8"


# singleton instance ---------------------------------------------------------

settings = Settings()

# Ensure default inventory path exists (helps with early errors)
_default_inventory = Path(settings.INVENTORY_FILE)
if not _default_inventory.exists():
    _default_inventory.parent.mkdir(parents=True, exist_ok=True)

