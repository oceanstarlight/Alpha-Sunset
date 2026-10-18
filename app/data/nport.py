"""SEC EDGAR N-PORT 보유내역 수집.

분기 데이터셋(수백 MB zip) 대신 필요한 펀드의 NPORT-P 공시 XML만 개별로 받는다.
SEC 요청은 User-Agent에 연락처가 필수(`SEC_USER_AGENT`)이고 초당 10회 이하로 제한된다.
"""

from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

import httpx
import pandas as pd

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers_mf.json"
BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
REQUEST_INTERVAL_SEC = 0.2


@dataclass(frozen=True)
class FundId:
    ticker: str
    cik: int
    series_id: str


@dataclass(frozen=True)
class Filing:
    filing_date: date
    folder_url: str  # .../Archives/edgar/data/{cik}/{accession}/


class SecClient:
    def __init__(self, user_agent: str | None = None, http: httpx.Client | None = None, interval_sec: float = REQUEST_INTERVAL_SEC):
        ua = user_agent or os.environ.get("SEC_USER_AGENT")
        if not ua:
            raise RuntimeError("SEC_USER_AGENT(이름 + 이메일)가 필요하다")
        self._http = http or httpx.Client(timeout=120, headers={"User-Agent": ua}, follow_redirects=True)
        self._interval = interval_sec
        self._last = 0.0

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        wait = self._interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        resp = self._http.get(url, params=params)
        resp.raise_for_status()
        return resp

    def resolve_funds(self, tickers: list[str]) -> dict[str, FundId]:
        data = self.get(TICKER_MAP_URL).json()
        cols = data["fields"]
        out = {}
        for row in data["data"]:
            r = dict(zip(cols, row))
            if r["symbol"] in tickers and r["symbol"] not in out:
                out[r["symbol"]] = FundId(ticker=r["symbol"], cik=int(r["cik"]), series_id=r["seriesId"])
        missing = set(tickers) - set(out)
        if missing:
            raise ValueError(f"SEC 티커 맵에 없는 펀드: {sorted(missing)}")
        return out

    def list_filings(self, series_id: str, page_size: int = 40) -> list[Filing]:
        """시리즈의 NPORT-P 공시 목록 (최신순)."""
        filings: list[Filing] = []
        start = 0
        while True:
            xml = self.get(BROWSE_URL, params={
                "action": "getcompany", "CIK": series_id, "type": "NPORT-P", "owner": "include",
                "count": page_size, "start": start, "output": "atom",
            }).text
            page = parse_filing_feed(xml)
            filings += page
            if len(page) < page_size:
                return filings
            start += page_size

    def holdings(self, filing: Filing) -> tuple[dict, pd.DataFrame]:
        return parse_nport(self.get(filing.folder_url + "primary_doc.xml").text)


def parse_filing_feed(xml: str) -> list[Filing]:
    dates = re.findall(r"<filing-date>([^<]+)</filing-date>", xml)
    hrefs = re.findall(r"<filing-href>([^<]+)</filing-href>", xml)
    return [Filing(date.fromisoformat(d), h.rsplit("/", 1)[0] + "/") for d, h in zip(dates, hrefs)]


def pick_filing(filings: list[Filing], before: date | None) -> Filing | None:
    """before 이전에 공개된 가장 최근 공시 (미래 정보 누수 방지). before=None이면 최신."""
    candidates = [f for f in filings if before is None or f.filing_date < before]
    return max(candidates, key=lambda f: f.filing_date, default=None)


def _text(el: ET.Element, tag: str) -> str | None:
    found = el.find(f"{{*}}{tag}")
    return found.text.strip() if found is not None and found.text else None


def _float(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "N/A") else None
    except ValueError:
        return None


def parse_nport(xml: str) -> tuple[dict, pd.DataFrame]:
    """NPORT-P primary_doc.xml → (메타, 보유내역 DataFrame)."""
    root = ET.fromstring(xml)
    gen = root.find(".//{*}genInfo")
    fund = root.find(".//{*}fundInfo")
    meta = {
        "series_id": _text(gen, "seriesId") if gen is not None else None,
        "series_name": _text(gen, "seriesName") if gen is not None else None,
        "rep_pd_date": _text(gen, "repPdDate") if gen is not None else None,
        "net_assets_usd": _float(_text(fund, "netAssets")) if fund is not None else None,
    }
    rows = []
    for sec in (el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "invstOrSec"):
        isin = sec.find(".//{*}isin")
        rows.append({
            "issuer": _text(sec, "name"),
            "title": _text(sec, "title"),
            "lei": _text(sec, "lei"),
            "cusip": _text(sec, "cusip"),
            "isin": isin.get("value") if isin is not None else None,
            "val_usd": _float(_text(sec, "valUSD")),
            "pct_val": _float(_text(sec, "pctVal")),
            "asset_cat": _text(sec, "assetCat"),
            "issuer_cat": _text(sec, "issuerCat"),
            "country": _text(sec, "invCountry"),
        })
    return meta, pd.DataFrame(rows)
