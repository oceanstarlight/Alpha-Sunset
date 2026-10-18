"""한국(로컬) 시장 데이터 클라이언트 — 공식 무료 소스만 (사전 등록 v5).

- OpenDART: 상장사 공시 목록 (신용 사건 경고)
- 네이버 검색 API: 뉴스 검색
- Google 뉴스 RSS: 뉴스 검색 (키 불필요)
- ECOS(한국은행): 지수·환율·금리·외국인 순매수 일별
- KRX Open API: 지수 일별 (ECOS 보조)

키가 없으면 KeyMissing을 던진다. 호출부는 '미설정'으로 기록하고 건너뛴다.
"""

from __future__ import annotations

import email.utils
import re
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
    provider: str  # naver | google


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


class NaverNewsClient:
    URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)

    def search(self, query: str, since: datetime, max_items: int = 1000) -> list[NewsItem]:
        """최신순으로 since 이후 기사만 (API 한도: start ≤ 1000, display ≤ 100)."""
        headers = {"X-Naver-Client-Id": _key("NAVER_CLIENT_ID"), "X-Naver-Client-Secret": _key("NAVER_CLIENT_SECRET")}
        out: list[NewsItem] = []
        for start in range(1, max_items + 1, 100):
            resp = self._http.get(self.URL, params={"query": query, "display": 100, "start": start, "sort": "date"},
                                  headers=headers)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for it in items:
                published = email.utils.parsedate_to_datetime(it["pubDate"])
                if published < since:
                    return out
                url = it.get("originallink") or it["link"]
                out.append(NewsItem(_strip_tags(it["title"]), url, _domain(url), published, "naver"))
            if len(items) < 100:
                break
        return out


class GoogleNewsRss:
    URL = "https://news.google.com/rss/search"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30, follow_redirects=True)

    def search(self, query: str, since: datetime) -> list[NewsItem]:
        """한국어·한국판 검색 RSS (최대 약 100건). 언론사는 <source> 이름."""
        days = max(1, -(-int((datetime.now(timezone.utc) - since).total_seconds()) // 86400))  # 올림
        resp = self._http.get(self.URL, params={"q": f"{query} when:{days}d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        resp.raise_for_status()
        out = []
        for item in ET.fromstring(resp.content).iter("item"):
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
            if published < since:
                continue
            src = item.find("source")
            source = (src.text or "").strip() if src is not None else _domain(item.findtext("link", ""))
            out.append(NewsItem(item.findtext("title", ""), item.findtext("link", ""), source, published, "google"))
        return out


def search_news(query: str, since: datetime, naver: NaverNewsClient | None, google: GoogleNewsRss | None) -> tuple[list[NewsItem], list[str]]:
    """'A | B | C' 쿼리를 나눠 두 소스에서 검색하고 제목 기준으로 중복 제거. 반환: (기사, 실패·미설정 사유)."""
    items: dict[str, NewsItem] = {}
    notes: list[str] = []
    for term in [t.strip() for t in query.split("|") if t.strip()]:
        for name, client in (("naver", naver), ("google", google)):
            if client is None:
                continue
            try:
                for it in client.search(term, since):
                    items.setdefault(re.sub(r"\W+", "", it.title)[:60], it)
            except KeyMissing as e:
                notes.append(str(e))
            except Exception as e:  # 한 소스 실패는 기록하고 계속
                notes.append(f"{name} '{term}': {e}")
    return list(items.values()), sorted(set(notes))


# ---------- ECOS · KRX ----------


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


class KrxClient:
    """KRX Open API (AUTH_KEY 헤더). 일별 지수 — ECOS 보조·교차 확인용."""

    URL = "https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd"

    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=30)

    def kospi(self, day: date) -> dict[str, float]:
        resp = self._http.get(self.URL, params={"basDd": f"{day:%Y%m%d}"}, headers={"AUTH_KEY": _key("KRX_API_KEY")})
        data = resp.json()
        if "OutBlock_1" not in data:
            raise RuntimeError(f"KRX 오류: {data.get('respMsg', data)}")
        return {r["IDX_NM"]: float(str(r["CLSPRC_IDX"]).replace(",", "")) for r in data["OutBlock_1"]
                if r.get("CLSPRC_IDX") not in (None, "", "-")}
