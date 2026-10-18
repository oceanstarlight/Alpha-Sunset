from datetime import date, datetime, timedelta

import httpx
import numpy as np
import pandas as pd

from app.agents import local
from app.agents.sentinel import AlertLevel, MarketSignal
from app.data import korea
from app.data.korea import KST, Disclosure, NewsItem
from app.notify import Notifier, format_message
from app.report import build_report

NOW = datetime(2026, 10, 19, 10, 0, tzinfo=KST)


def _series(n=400, seed=0, end="2026-10-16", shock=None):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=end, periods=n)
    vals = 100 + rng.normal(0, 1, n).cumsum()
    if shock:
        vals[-1] = vals[-2] + shock
    return pd.Series(vals, index=idx)


def test_kr_market_signal_uses_global_thresholds_and_derived_credit():
    raw = {"KOSPI": _series(seed=1, shock=-40), "USDKRW": _series(seed=2, shock=30), "KTB3Y": _series(seed=3),
           "CORP_AA3Y": _series(seed=4), "CD91": _series(seed=5)}
    panel = local.kr_panel(raw)
    assert "CREDIT_KR" in panel
    sig = local.kr_market_signal(panel, date(2026, 10, 16))
    assert {"KOSPI", "USDKRW"} <= set(sig.triggered) and sig.active


def test_kr_news_needs_baseline_then_spike_and_sources():
    def items(n, n_src):
        return [NewsItem(f"t{i}", f"https://s{i % n_src}.kr/{i}", f"s{i % n_src}.kr", NOW, "google") for i in range(n)]

    sig, rows = local.kr_news_signal({"credit_event": items(50, 15)}, [], NOW)
    assert sig.status == "unavailable" and "기준선 축적 중" in sig.notes[0] and len(rows) == 1
    history = [{"ts": (NOW - timedelta(days=d)).isoformat(), "event_type": "credit_event", "n_articles": 10 + d % 3, "n_sources": 8}
               for d in range(1, 26)]
    assert local.kr_news_signal({"credit_event": items(50, 15)}, history, NOW)[0].active
    assert not local.kr_news_signal({"credit_event": items(50, 5)}, history, NOW)[0].active  # 언론사 10곳 미만


def test_dart_warning_only_until_news_confirms():
    d = Disclosure("가나건설", "000001", "Y", "주요사항보고서(회생절차개시신청)", "20261019000001", date(2026, 10, 19))
    other = Disclosure("다라", "000002", "Y", "주요사항보고서(유상증자결정)", "20261019000002", date(2026, 10, 19))
    unlisted = Disclosure("마바", "", "E", "주요사항보고서(부도발생)", "20261019000003", date(2026, 10, 19))
    ws = local.dart_warnings([d, other, unlisted])
    assert [w.keyword for w in ws] == ["회생절차개시신청"]
    few = [NewsItem("가나건설 회생 신청", f"https://a{i}.kr", f"a{i}.kr", NOW, "naver") for i in range(3)]
    assert not local.confirm_warning(ws[0], few, NOW).confirmed
    many = [NewsItem("가나건설 회생 신청", f"https://a{i}.kr", f"a{i}.kr", NOW, "naver") for i in range(12)]
    w = local.confirm_warning(ws[0], many, NOW)
    assert w.confirmed and w.n_sources == 12
    # 경고만 있으면 WATCH, 확정 + 한국 시장 반응이면 ALERT
    calm = MarketSignal(date(2026, 10, 19), {"KOSPI": 0.5}, [], False)
    hot = MarketSignal(date(2026, 10, 19), {"KOSPI": -4.5}, ["KOSPI"], True)
    unconfirmed = local.DartWarning(d, "회생절차개시신청")
    assert local.local_grade(calm, None, None, False, [unconfirmed]) == AlertLevel.WATCH
    assert local.local_grade(hot, None, None, False, [unconfirmed]) == AlertLevel.WATCH  # 경고 단독으론 대응안 없음
    assert local.local_grade(hot, None, None, False, [w]) == AlertLevel.ALERT


def test_global_event_alert_attaches_linkage_evidence():
    g = {"VIXCLS": _series(seed=7), "DGS10": _series(seed=8)}
    kr = {"KOSPI": 300 - g["VIXCLS"] + _series(seed=9) * 0.1, "KTB3Y": _series(seed=10)}
    links = local.historical_link(g, kr, date(2026, 10, 19))
    vix = next(x for x in links if x["pair"].startswith("VIX"))
    assert vix["corr"] < -0.3 and vix["percentile"] is not None
    assert next(x for x in links if "달러 인덱스" in x["pair"])["note"] == "데이터 없음"
    gm = MarketSignal(date(2026, 10, 19), {"VIXCLS": 3.2}, ["VIXCLS"], True)
    km = MarketSignal(date(2026, 10, 19), {"KOSPI": -3.0, "USDKRW": 2.8}, ["KOSPI", "USDKRW"], True)
    lk = local.linkage_evidence(gm, km, links, kr_exposure=0.41)
    assert not lk["weak"] and lk["co_movement"]["korea"] == {"KOSPI": -3.0, "USDKRW": 2.8}
    r = local.LocalResult(NOW, local.local_grade(km, None, None, True, []), km, None, None, True, [], lk)
    chain = local.explain_local(r)
    assert r.level == AlertLevel.ALERT
    assert any(c["단계"] == "해외-한국 연관성" and "인과" in c["근거"] for c in chain)
    assert all(set(c) == {"단계", "원인", "근거", "결과"} for c in chain)
    report = build_report("테스트", NOW, chain, lk)
    assert "해외-한국 연관성 근거" in report and "| 단계 | 원인 | 근거 | 결과 |" in report


def test_notifier_dedupes_and_skips_without_keys(tmp_path, monkeypatch):
    sent = []

    def handler(req):
        sent.append(req)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    n = Notifier(tmp_path / "s.json", http=httpx.Client(transport=httpx.MockTransport(handler)), now=NOW)
    assert n.send("k", "x") == "not_configured"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    assert n.send("k", "x") == "sent" and n.send("k", "x") == "duplicate" and len(sent) == 1
    msg = format_message("제목", [{"단계": "A", "원인": "c", "근거": "e", "결과": "r"}], "http://r")
    assert "원인: c" in msg and "근거: e" in msg and "리포트: http://r" in msg


def test_dart_client_paginates_and_parses():
    def handler(req):
        page = int(req.url.params["page_no"])
        return httpx.Response(200, json={"status": "000", "total_page": 2, "list": [
            {"corp_name": f"c{page}", "stock_code": "1", "corp_cls": "Y", "report_nm": "주요사항보고서(부도발생)",
             "rcept_no": f"2026101900000{page}", "rcept_dt": "20261019"}]})

    import os
    os.environ.setdefault("DART_API_KEY", "x")
    out = korea.DartClient(http=httpx.Client(transport=httpx.MockTransport(handler))).disclosures(date(2026, 10, 18), date(2026, 10, 19))
    assert [d.corp_name for d in out] == ["c1", "c2"] and out[0].url.endswith("20261019000001")


def test_search_news_records_missing_keys_and_dedupes(monkeypatch):
    monkeypatch.delenv("NAVER_CLIENT_ID", raising=False)

    class FakeGoogle:
        def search(self, q, since):
            return [NewsItem("같은 제목", "u1", "A", NOW, "google"), NewsItem("같은 제목", "u2", "B", NOW, "google")]

    items, notes = korea.search_news("부도 | 디폴트", NOW - timedelta(days=1), korea.NaverNewsClient(), FakeGoogle())
    assert len(items) == 1 and notes == ["NAVER_CLIENT_ID 미설정"]
