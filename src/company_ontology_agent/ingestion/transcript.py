from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_transcript_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return "\n".join(_message_to_text(item) for item in data)
    if isinstance(data, dict):
        for key in ("messages", "turns", "segments", "transcript"):
            value = data.get(key)
            if isinstance(value, list):
                return "\n".join(_message_to_text(item) for item in value)
        return json.dumps(data, ensure_ascii=False, indent=2)
    return str(data)


def _message_to_text(item: Any) -> str:
    if isinstance(item, dict):
        speaker = item.get("speaker") or item.get("author") or item.get("role") or "unknown"
        text = item.get("text") or item.get("content") or item.get("message") or ""
        return f"{speaker}: {text}"
    return str(item)
