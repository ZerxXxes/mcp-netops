"""Very lightweight audit trail.

Appends JSON lines to *audit.log* and emits a structured Loguru message. Uses
plain ``open(path, "a")`` to avoid the Path.write_text *append* gotcha.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_AUDIT_PATH = Path("audit.log").resolve()


def record(
    *,
    user: str,
    device: str,
    command: str,
    raw_output: str,
    parsed: Optional[dict[str, Any]] = None,
) -> None:  # noqa: D401
    """Persist an audit event to file and structured logger."""

    event = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "user": user,
        "device": device,
        "command": command,
        "raw_len": len(raw_output),
        "has_json": parsed is not None,
    }

    # Log for console/SIEM collectors
    logger.bind(audit=True).info("{event}", event=event)

    # Write JSONL
    try:
        _AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**event, "stdout": raw_output, "json": parsed}) + "\n")
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write audit log to %s", _AUDIT_PATH)

