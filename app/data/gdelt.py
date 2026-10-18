"""GDELT DOC 2.0 API 클라이언트 (라이브 모드 전용, 최근 약 3개월만 조회 가능)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pandas as pd

from app.config import load_config

DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    domain: str
    seen: datetime
    source_country: str = ""  # 보도 매체 국가 (사건 발생 위치가 아님)


class GdeltClient:
    def __init__(self, http: httpx.Client | None = None, interval_sec: float | None = None):
        self._http = http or httpx.Client(timeout=30)
        self._interval = (
            interval_sec if interval_sec is not None else load_config()["sentinel"]["news"]["request_interval_sec"]
        )
        self._last_request = 0.0

    def _get(self, params: dict, max_attempts: int = 4) -> dict:
        """요청 간격을 지키고, 429·연결 끊김은 점점 길게 기다렸다 재시도한다 (공유 IP 환경 대응)."""
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            wait = self._interval * attempt - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                resp = self._http.get(DOC_API_URL, params={**params, "format": "json"})
            except httpx.TransportError as e:  # 서버가 응답 없이 연결을 끊는 경우 등
                last_error = e
                continue
            if resp.status_code == 429:
                last_error = httpx.HTTPStatusError("429 Too Many Requests", request=resp.request, response=resp)
                continue
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError as e:
                # 요청 제한 초과 시 JSON 대신 안내 문구가 올 때가 있다
                last_error = RuntimeError(f"GDELT 응답이 JSON이 아니다: {resp.text[:120]}")
                continue
        raise RuntimeError(f"GDELT {max_attempts}회 시도 실패: {last_error}")

    @staticmethod
    def _query(q: str) -> str:
        # OR 조합은 괄호로 감싸야 한다
        return f"({q})" if " OR " in q and not q.startswith("(") else q

    def daily_volume(self, query: str, timespan: str = "3months") -> pd.Series:
        """일별 기사 수."""
        data = self._get({"query": self._query(query), "mode": "timelinevolraw", "timespan": timespan})
        points = data.get("timeline", [{}])[0].get("data", []) if data.get("timeline") else []
        s = pd.Series(
            {pd.Timestamp(p["date"]).tz_localize(None): p["value"] for p in points}, dtype="float64"
        )
        return s.resample("D").sum() if not s.empty else s

    def articles(self, query: str, timespan: str = "1d", max_records: int = 250) -> list[Article]:
        data = self._get({"query": self._query(query), "mode": "artlist", "timespan": timespan, "maxrecords": max_records})
        out = []
        for a in data.get("articles", []):
            seen = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            out.append(Article(title=a.get("title", ""), url=a["url"], domain=a.get("domain", ""), seen=seen,
                               source_country=a.get("sourcecountry", "")))
        return out
