"""LLM 응답 캐시: 입력 해시 → SQLite(`data/llm_cache.db`). 백테스트 재현성·비용 절감용."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def make_key(**parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, kind TEXT NOT NULL, model TEXT NOT NULL, "
            "response TEXT NOT NULL, ts TEXT NOT NULL)"
        )
        self._conn.commit()

    def get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT response FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, kind: str, model: str, response: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, kind, model, response, ts) VALUES (?, ?, ?, ?, ?)",
            (key, kind, model, response, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
