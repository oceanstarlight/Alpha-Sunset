"""한국(로컬) 시장 데이터 클라이언트 — 공식 무료 소스만 (사전 등록 v5).

- OpenDART: 상장사 공시 목록 (신용 사건 경고)
- Google 뉴스 RSS: 뉴스 검색 (키 불필요)
- ECOS(한국은행): 지수·환율·금리·외국인 순매수 일별

네이버 검색 API는 유료 전환으로, KRX Open API는 약관(비상업적 목적만 이용, 결과에 대한 대가 청구 금지)으로 사용하지 않는다 (사용자 결정).

키가 없으면 KeyMissing을 던진다. 호출부는 '미설정'으로 기록하고 건너뛴다.
"""

from __future__ import annotations

import email.utils
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
import pandas as pd

from app.config import get_secret

KST = timezone(timedelta(hours=9))


class KeyMissing(RuntimeError):
    pass


def _key(name: str) -> str:
    value = get_secret(name)
    if not value:
        raise KeyMissing(f"{name} 미설정")
    return value


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).replace("&quot;", '"').replace("&amp;", "&").strip()


@dataclass(frozen=True)
class NewsItem:
    title: str
    url: str
    source: str  # 언론사 도메인 또는 이름
    published: datetime
    provider: str  # google


@dataclass(frozen=True)
class Disclosure:
    corp_name: str
    stock_code: str
    corp_cls: str
    report_nm: str
    rcept_no: str
    rcept_dt: date

    @property
    def url(self) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.rcept_no}"


# ---------- OpenDART ----------


class DartClient:
    URL = "https://opendart.fss.or.kr/api/list.json"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)

    def disclosures(self, start: date, end: date, kind: str = "B", max_pages: int = 20) -> list[Disclosure]:
        """기간 공시 목록. kind B = 주요사항보고서 (부도·회생·영업정지 등)."""
        key = _key("DART_API_KEY")
        out: list[Disclosure] = []
        for page in range(1, max_pages + 1):
            data = self._http.get(self.URL, params={
                "crtfc_key": key, "bgn_de": f"{start:%Y%m%d}", "end_de": f"{end:%Y%m%d}",
                "pblntf_ty": kind, "page_no": page, "page_count": 100}).json()
            if data.get("status") == "013":  # 조회된 데이터 없음
                break
            if data.get("status") != "000":
                raise RuntimeError(f"DART 오류 {data.get('status')}: {data.get('message')}")
            for x in data.get("list", []):
                out.append(Disclosure(x["corp_name"], x.get("stock_code", ""), x.get("corp_cls", ""), x["report_nm"],
                                      x["rcept_no"], datetime.strptime(x["rcept_dt"], "%Y%m%d").date()))
            if page >= int(data.get("total_page", 1)):
                break
        return out


# ---------- 뉴스 ----------


class GoogleNewsRss:
    URL = "https://news.google.com/rss/search"

    def __init__(self, http: httpx.Client | None = None, lang: str = "ko", region: str = "KR"):
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)
        self._lang, self._region = lang, region

    def search(self, query: str, since: datetime) -> list[NewsItem]:
        """검색 RSS (최대 약 100건, 기본 한국어·한국판). 언론사는 <source> 이름."""
        days = max(1, -(-int((datetime.now(timezone.utc) - since).total_seconds()) // 86400))  # 올림
        params = {"q": f"{query} when:{days}d", "hl": self._lang, "gl": self._region,
                  "ceid": f"{self._region}:{self._lang.split('-')[0]}"}
        for attempt in range(2):  # 일시 오류(429·5xx·연결 끊김)는 2초 뒤 한 번 더
            try:
                resp = self._http.get(self.URL, params=params)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    time.sleep(2)
                    continue
                resp.raise_for_status()
                break
            except httpx.TransportError:
                if attempt:
                    raise
                time.sleep(2)
        out = []
        for item in ET.fromstring(resp.content).iter("item"):
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
            if published < since:
                continue
            src = item.find("source")
            source = (src.text or "").strip() if src is not None else _domain(item.findtext("link", ""))
            out.append(NewsItem(item.findtext("title", ""), item.findtext("link", ""), source, published, "google"))
        return out


def search_news(query: str, since: datetime, google: GoogleNewsRss | None) -> tuple[list[NewsItem], list[str]]:
    """'A | B | C' 쿼리를 나눠 검색하고 제목 기준으로 중복 제거. 반환: (기사, 실패 사유).

    Google 뉴스 RSS는 검색어당 최대 약 100건이라, 매우 큰 사건에서는 기사 수가 상한에 걸려 z가 눌릴 수 있다.
    """
    items: dict[str, NewsItem] = {}
    notes: list[str] = []
    if google is None:
        return [], ["Google 뉴스 RSS 미사용"]
    for term in [t.strip() for t in query.split("|") if t.strip()]:
        try:
            for it in google.search(term, since):
                items.setdefault(re.sub(r"\W+", "", it.title)[:60], it)
        except Exception as e:  # 한 검색어 실패는 기록하고 계속
            notes.append(f"google '{term}': {e}")
    return list(items.values()), sorted(set(notes))


# ---------- ECOS ----------


class EcosClient:
    URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/{stat}/D/{start}/{end}/{item}"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=60)

    def series(self, stat: str, item: str, start: date, end: date) -> pd.Series:
        url = self.URL.format(key=_key("ECOS_API_KEY"), stat=stat, start=f"{start:%Y%m%d}", end=f"{end:%Y%m%d}", item=item)
        data = self._http.get(url).json()
        if "StatisticSearch" not in data:
            raise RuntimeError(f"ECOS 오류: {data.get('RESULT', data)}")
        rows = data["StatisticSearch"]["row"]
        s = pd.Series({pd.Timestamp(r["TIME"]): float(r["DATA_VALUE"]) for r in rows if r.get("DATA_VALUE") not in (None, "")},
                      dtype="float64").sort_index()
        s.index.name = "date"
        return s
