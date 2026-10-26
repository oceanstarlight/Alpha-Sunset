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
    """디스크 쓰기가 불가(읽기전용 배포 FS·락 경합)해도 죽지 않도록 메모리 캐시로 폴백한다."""

    def __init__(self, path: Path):
        self._mem: dict[str, str] = {}
        self._conn: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                "key TEXT PRIMARY KEY, kind TEXT NOT NULL, model TEXT NOT NULL, "
                "response TEXT NOT NULL, ts TEXT NOT NULL)"
            )
            conn.commit()
            self._conn = conn
        except (sqlite3.Error, OSError):
            self._conn = None  # 읽기/쓰기 모두 메모리로

    def get(self, key: str) -> str | None:
        if key in self._mem:
            return self._mem[key]
        if self._conn is None:
            return None
        try:
            row = self._conn.execute("SELECT response FROM cache WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    def set(self, key: str, kind: str, model: str, response: str) -> None:
        self._mem[key] = response
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, kind, model, response, ts) VALUES (?, ?, ?, ?, ?)",
                (key, kind, model, response, datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
        except sqlite3.Error:
            pass  # 캐시는 최적화일 뿐 — 디스크 기록 실패는 메모리 캐시로 충분

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
