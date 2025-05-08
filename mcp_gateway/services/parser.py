"""Best‑effort CLI parsers.

In a *proper* implementation you would hook pyATS Genie or TextFSM templates.
For the PoC we implement only one concrete normaliser – ``show ip int brief`` –
and fall back to ``None``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from loguru import logger

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def maybe_parse(*, command: str, raw: str, platform: str) -> Optional[dict[str, Any]]:  # noqa: D401
    """Return JSON if we know how to parse ``command`` for *platform* else ``None``."""

    command = command.strip().lower()

    if command.startswith("show ip int brief"):
        return _parse_show_ip_int_brief(raw)

    # Add more elif blocks or register dynamic parsers later.
    logger.debug("No parser for command=%s on platform=%s", command, platform)
    return None


# ---------------------------------------------------------------------------
# Concrete parser implementations
# ---------------------------------------------------------------------------


_HEADER_RE = re.compile(r"^Interface +IP-Address +OK\? +Method +Status +Protocol", re.I)


def _parse_show_ip_int_brief(raw: str) -> dict[str, Any]:
    """Hand‑rolled parser that returns list of interfaces with status/addr."""

    lines = raw.splitlines()
    try:
        hdr_idx = next(i for i, l in enumerate(lines) if _HEADER_RE.match(l))
    except StopIteration:
        logger.debug("Could not locate header line in 'show ip int brief' output")
        return {}

    entries = []
    for line in lines[hdr_idx + 1 :]:
        if not line.strip():
            continue
        parts = re.split(r"\s+", line, maxsplit=5)
        if len(parts) < 6:
            continue
        iface, ip_addr, ok, method, status, protocol = parts
        entries.append(
            {
                "interface": iface,
                "ip_address": ip_addr,
                "ok": ok,
                "method": method,
                "status": status,
                "protocol": protocol,
            }
        )

    return {"interfaces": entries}

