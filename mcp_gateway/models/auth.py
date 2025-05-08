"""User model shared between auth service and route dependencies."""
from __future__ import annotations

from pydantic import BaseModel, Field


class User(BaseModel):
    """Authenticated caller context injected via Depends()."""

    username: str = Field(..., description="Caller username or service account ID")
    roles: list[str] = Field(default_factory=list, description="Global roles, e.g. 'admin'")
    allowed_tags: list[str] = Field(
        default_factory=list,
        description="RBAC labels; device is allowed if any tag matches",
    )

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }

