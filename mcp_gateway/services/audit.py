"""Very lightweight audit trail.

For the PoC we simply append JSON lines to *audit.log* and also emit a
structured message via Loguru so that stdout/stderr streams are still useful in
Docker/k8s.  A production build would push these events to Loki or a SIEM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from loguru import logger

# Path is relative to project root
_AUDIT_PATH = Path("audit.log").resolve()


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


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

    # Emit Loguru record (already timestamped)
    logger.bind(audit=True).info("{event}", event=event)

    # Append JSON line to file (quick & dirty persistence)
    try:
        _AUDIT_PATH.touch(exist_ok=True)
        _AUDIT_PATH.write_text(json.dumps({**event, "stdout": raw_output, "json": parsed}) + "\n", append=True)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write audit log to %s", _AUDIT_PATH)

