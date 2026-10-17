"""FRED 시계열 수집·캐시. `fredgraph.csv` 엔드포인트는 API 키 없이 동작한다."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pandas as pd

from app.config import ROOT_DIR

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CACHE_DIR = ROOT_DIR / "data" / "fred"


def _cache_path(series_id: str, cache_dir: Path) -> Path:
    return cache_dir / f"{series_id}.csv"


def fetch_series(series_id: str, cache_dir: Path = CACHE_DIR) -> pd.Series:
    """FRED에서 전체 이력을 내려받아 캐시에 저장한다."""
    resp = httpx.get(FRED_CSV_URL, params={"id": series_id}, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    cache_dir.mkdir(parents=True, exist_ok=True)
    _cache_path(series_id, cache_dir).write_text(resp.text, encoding="utf-8")
    return _parse(io.StringIO(resp.text), series_id)


def load_series(series_id: str, cache_dir: Path = CACHE_DIR, refresh: bool = False) -> pd.Series:
    """캐시 우선. 캐시가 없거나 refresh=True면 내려받는다."""
    path = _cache_path(series_id, cache_dir)
    if refresh or not path.exists():
        return fetch_series(series_id, cache_dir)
    return _parse(path, series_id)


def load_panel(series_ids: list[str], cache_dir: Path = CACHE_DIR, refresh: bool = False) -> dict[str, pd.Series]:
    """시리즈별 관측일이 달라 DataFrame으로 합치지 않고 dict로 반환한다."""
    return {sid: load_series(sid, cache_dir, refresh) for sid in series_ids}


def _parse(src, series_id: str) -> pd.Series:
    df = pd.read_csv(src, index_col=0, parse_dates=True, na_values=".")
    s = pd.to_numeric(df.iloc[:, 0], errors="coerce").dropna()
    s.index.name = "date"
    s.name = series_id
    return s
