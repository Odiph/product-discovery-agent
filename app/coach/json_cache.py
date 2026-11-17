"""The two moves every model-answer cache under `context/` shares: read a
versioned JSON file tolerantly, and write one atomically (temp file in the
same directory, fsync, `os.replace`). Used by `prompt_judge_store` and
`coverage_store`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

ABSENT = "absent"
FRESH = "fresh"
STALE = "stale"
UNREADABLE = "unreadable"


def read(path: Path, version: int, what: str) -> "tuple[Optional[dict], str, str]":
    """(payload, status, reason): payload only when the file is a version-`version`
    JSON object; otherwise `ABSENT` or `UNREADABLE` with a reason naming the file."""
    path = Path(path)
    if not path.is_file():
        return None, ABSENT, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, UNREADABLE, f"{path.name} cannot be read ({type(exc).__name__})"
    if not isinstance(payload, dict) or payload.get("version") != version:
        return None, UNREADABLE, f"{path.name} is not a version-{version} {what}"
    return payload, FRESH, ""


def write(path: Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)
    return path
