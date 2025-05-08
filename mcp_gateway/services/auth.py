"""Very small auth layer for the PoC.

We pretend every request carries either:
    * a valid **Bearer** JWT (HS256) in ``Authorization`` header – *or*
    * nothing, in which case we fall back to a hard‑coded *demo* user.

**⚠️  Do *NOT* ship this to production** – add real identity provider + key
rotation first.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from loguru import logger

from mcp_gateway.config import settings  # type: ignore
from mcp_gateway.models.auth import User


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

_JWT_SECRET = settings.JWT_SECRET  # plain string for HS256 PoC
_JWT_ALGO = "HS256"


# ---------------------------------------------------------------------------
# Security scheme for FastAPI docs
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def create_token(user: User, *, ttl_sec: int = 3600) -> str:  # noqa: D401
    """Issue a *very* simple HS256 token for test clients."""
    payload = {
        "sub": user.username,
        "roles": user.roles,
        "tags": user.allowed_tags,
        "exp": int(datetime.now(tz=timezone.utc).timestamp() + ttl_sec),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


async def get_current_user(
    request: Request,  # Need raw headers for FaaS / proxy compatibility
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
) -> User:  # noqa: D401
    """FastAPI dependency that validates JWT and returns a :class:`User`.

    In PoC mode: if no ``Authorization`` header is present, return a fixed
    *demo* user with ``roles=["admin"]`` for convenience.
    """

    if creds is None:
        logger.debug("No JWT presented – using demo user")
        return User(username="demo", roles=["admin"], allowed_tags=["*"])

    token = creds.credentials
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc

    exp = payload.get("exp")
    if exp and datetime.now(tz=timezone.utc).timestamp() > exp:
        raise HTTPException(status_code=401, detail="Token expired")

    return User(
        username=payload.get("sub", "anon"),
        roles=payload.get("roles", []),
        allowed_tags=payload.get("tags", []),
    )

