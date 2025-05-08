"""ASGI entry‑point for the MCP‑NetOps proof‑of‑concept.

Run in dev mode:
    uvicorn mcp_gateway.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mcp_gateway.routes import mcp_routes
from mcp_gateway.config import settings


app = FastAPI(
    title="MCP‑NetOps PoC",
    version="0.1.0",
    description="Middle‑layer gateway exposing Model‑Context‑Protocol endpoints for network devices.",
)

# ---------------------------------------------------------------------------
# Middleware (CORS for browser‑based test clients)
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(mcp_routes.router, prefix="/mcp")


# ---------------------------------------------------------------------------
# Root & liveness endpoints
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def _root() -> dict[str, str]:
    return {"service": "mcp‑netops", "status": "alive"}

