"""Small deterministic helpers shared by adapters and storage."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: Any, prefix: str = "") -> str:
    raw = "\x1f".join("" if part is None else str(part) for part in parts)
    value = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"{prefix}{value}"


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Millisecond timestamps are common in prompt history files.
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def jsonable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(jsonable_text(item) for item in value if item is not None)
    if isinstance(value, dict):
        for key in ("text", "content", "output", "message"):
            if key in value:
                return jsonable_text(value[key])
    return str(value)
