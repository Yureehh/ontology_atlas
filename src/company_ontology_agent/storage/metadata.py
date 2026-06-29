from __future__ import annotations

import sqlite3
from pathlib import Path


def init_metadata_store(project_root: Path) -> None:
    db_path = project_root / "data" / "processed" / "metadata.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS source_state (source_id TEXT PRIMARY KEY, sha256 TEXT)"
        )
