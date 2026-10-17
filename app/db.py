"""SQLite 접근. 라이브(`live.db`)와 백테스트/시뮬레이션(`sandbox.db`)은 절대 섞지 않는다."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from app.config import get_settings

DbMode = Literal["live", "sandbox"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    model TEXT NOT NULL,
    in_tokens INTEGER NOT NULL DEFAULT 0,
    out_tokens INTEGER NOT NULL DEFAULT 0,
    purpose TEXT NOT NULL,
    cache_hit INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    cited INTEGER NOT NULL,
    rank INTEGER,
    feedback TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('live', 'backtest', 'sim')),
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    label TEXT NOT NULL CHECK (label IN ('useful', 'not_fit')),
    user_id TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefings (
    run_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    tool TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces (trace_id);
CREATE TABLE IF NOT EXISTS learner_toggle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enabled INTEGER NOT NULL,
    ts TEXT NOT NULL
);
"""


def db_path(mode: DbMode) -> Path:
    settings = get_settings()
    if mode == "live":
        return settings.live_db
    if mode == "sandbox":
        return settings.sandbox_db
    raise ValueError(f"알 수 없는 DB 모드: {mode}")


def connect(mode: DbMode) -> sqlite3.Connection:
    """모드에 맞는 DB에 연결하고 스키마를 보장한다."""
    path = db_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
