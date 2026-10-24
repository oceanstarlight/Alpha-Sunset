"""Alpha Sunset — Streamlit UI (7탭: 세계 금융 지도 / 감시 / 브리핑 / 승인 / 백테스트 / 학습 층 / 데이터 입력)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # Streamlit Cloud: 저장소 루트를 import 경로에


def _code_stamp() -> str:
    """app/ 코드와 config.yaml의 수정 상태. 바뀌면 app 모듈을 새로 불러온다.

    Streamlit은 메인 스크립트 폴더(ui/) 밖 모듈을 다시 불러오지 않아, 새 커밋을 받아도 예전 app 코드가 메모리에 남는다.
    """
    files = sorted(ROOT.joinpath("app").rglob("*.py")) + [ROOT / "config.yaml"]
    return str(hash(tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.exists())))


_STAMP = _code_stamp()
if "app" in sys.modules and getattr(sys.modules["app"], "_code_stamp", _STAMP) != _STAMP:  # UI가 불러온 뒤 코드가 바뀐 경우만
    for _name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[_name]
    _RELOADED = True
else:
    _RELOADED = False

import pandas as pd
import pydeck as pdk
import streamlit as st

from app import audit, dashboard, export, geo, services
from app.config import get_settings, load_config
from app.agents import sentinel
from app.agents.exposure import ExposureUnavailable
from app.corpus import load_events, load_playbooks, load_portfolio
from app.schemas import AlertLevel, Briefing, Event, Feedback, Verdict

sys.modules["app"]._code_stamp = _STAMP
if _RELOADED:
    load_config.cache_clear()
    st.cache_data.clear()
    st.cache_resource.clear()

st.set_page_config(page_title="Alpha Sunset", page_icon="🌅", layout="wide")

VERDICT_LABEL = {
    Verdict.applicable: "✅ 적용",
    Verdict.partial: "🟡 부분적용",
    Verdict.not_applicable: "❌ 부적용",
    Verdict.uncertain: "❔ 불확실",
}
LEVEL_COLOR = {AlertLevel.ALERT: "red", AlertLevel.WATCH: "orange", AlertLevel.NONE: "gray"}


# ---------- 데이터 (캐시) ----------


@st.cache_resource
def events_by_id():
    return {e.id: e for e in sorted(load_events(), key=lambda e: e.date)}


@st.cache_resource
def clauses_by_id():
    return {c.clause_id: c for p in load_playbooks() for c in p.clauses}


@st.cache_resource
def docs_by_id():
    return {p.doc_id: p for p in load_playbooks()}


@st.cache_resource
def market_panel():
    return services.market_panel()


@st.cache_data(show_spinner=False)
def replay_signals(event_id: str) -> pd.DataFrame:
    e = events_by_id()[event_id]
    results = sentinel.replay(market_panel(), [e], e.date - timedelta(days=30), e.date + timedelta(days=14))
    return pd.DataFrame([{"날짜": r.as_of, "등급": r.level.value,
                          "자금 이상 알림": r.market.active or bool(r.flow and r.flow.active),
                          "시장 신호(A)": r.market.active, "자금 흐름(C)": bool(r.flow and r.flow.active),
                          "사건 확정(B)": r.news.active,
                          "트리거": ", ".join(r.market.triggered + (r.flow.triggered if r.flow else []))} for r in results])


@st.cache_data(show_spinner=False)
def replay_chains(event_id: str) -> dict[str, list[dict]]:
    """재생 구간의 첫 자금 이상 알림일·첫 ALERT일 판단 근거."""
    e = events_by_id()[event_id]
    results = sentinel.replay(market_panel(), [e], e.date - timedelta(days=30), e.date + timedelta(days=14))
    out = {}
    first_money = next((r for r in results if r.market.active or (r.flow and r.flow.active)), None)
    first_alert = next((r for r in results if r.level == AlertLevel.ALERT), None)
    for name, r in [("첫 자금 이상 알림", first_money), ("첫 ALERT", first_alert)]:
        if r:
            out[f"{name} ({r.as_of})"] = sentinel.explain(r)
    return out


def show_chain(chain: list[dict]) -> None:
    """원인 → 근거 → 결과 표."""
    st.dataframe(pd.DataFrame(chain), hide_index=True, width="stretch",
                 column_config={"근거": st.column_config.TextColumn(width="large")})


def summary_box(s: dashboard.Summary) -> None:
    """탭 맨 위 요약: 지금 상태 → 이유 → 할 일."""
    with st.container(border=True):
        st.markdown(f"#### {s.icon} {s.headline}")
        st.markdown("\n".join(f"- {x}" for x in s.bullets))


def chart(c, col=None) -> None:
    if c is not None:
        (col or st).altair_chart(c, width="stretch")


def synthetic_badge():
    st.badge("합성 데이터: 대응문서·포트폴리오·라벨은 가상으로 재구성", icon="⚠️", color="orange")


# ---------- 사이드바 ----------

st.sidebar.title("🌅 Alpha Sunset")
st.sidebar.caption("위기 사건 ↔ 대응문서 적합도 판단 + 보유 자산 노출 경고")
LOCAL = load_config()["markets"]["local"]
market_view = st.sidebar.radio(
    "시장", ["local", "global"], horizontal=True, help="데이터는 로컬·글로벌 모두 수집하고, 화면에 보여줄 범위만 고른다.",
    format_func=lambda v: f"로컬 ({LOCAL['name']})" if v == "local" else "글로벌",
    index=0 if load_config()["markets"]["default_view"] == "local" else 1)
is_local = market_view == "local"
mode = st.sidebar.radio("모드", ["백테스트 재생", "라이브"], horizontal=True)
event_ids = list(events_by_id())
event_id = st.sidebar.selectbox(
    "사건", event_ids, format_func=lambda i: f"{events_by_id()[i].date} · {events_by_id()[i].title}",
    disabled=mode == "라이브",
)
user_id = st.sidebar.text_input("검토자", value="reviewer")
st.sidebar.divider()
st.sidebar.caption("에이전트는 제안만 하고 최종 결정은 사람이 승인한다. 문서를 삭제·폐기하지 않는다.")
_PROVIDER_LABEL = {"gemini": "Gemini", "openai_compatible": "OpenAI 호환", "rule": "규칙 판정(LLM 없음 · 신뢰도 0.3)"}
_st = get_settings()
st.sidebar.caption(f"판정 엔진: {_PROVIDER_LABEL.get(_st.llm_provider, _st.llm_provider)}"
                   + (f" · {_st.llm_model}" if _st.llm_provider == "openai_compatible" and _st.llm_model else ""))
st.sidebar.caption(f"코드 버전 {abs(int(_STAMP)) % 10**8:08d}" + (" · 새 코드 반영됨" if _RELOADED else ""))


def current_briefing() -> Briefing | None:
    key = "live_briefing" if mode == "라이브" else f"briefing_{event_id}"
    if mode != "라이브" and st.session_state.get("portfolio_choice") == "업로드" and f"{key}_upload" in st.session_state:
        return st.session_state[f"{key}_upload"]  # 업로드 포트폴리오 가정 분석 결과
    if key not in st.session_state and mode != "라이브":
        st.session_state[key] = services.load_saved_briefing(event_id)
    return st.session_state.get(key)


def uploaded_args() -> dict:
    """업로드 포트폴리오·대응 문서가 있으면 브리핑 실행에 넘길 인자."""
    args = {}
    pf = st.session_state.get("uploaded_portfolio")
    if pf is not None:
        args |= {"portfolio": pf, "holdings": st.session_state.get("uploaded_holdings")}
    pbs = st.session_state.get("uploaded_playbooks")
    if pbs:
        mode_ = st.session_state.get("doc_mode", "업로드 문서만")
        args["playbooks"] = pbs if mode_ == "업로드 문서만" else load_playbooks() + pbs
    return args


def all_clauses() -> dict:
    """합성 조항 + 업로드 문서 조항 (브리핑 표시용)."""
    out = dict(clauses_by_id())
    for p in st.session_state.get("uploaded_playbooks") or []:
        out |= {c.clause_id: c for c in p.clauses}
    return out


tab_map, tab_watch, tab_brief, tab_approve, tab_bt, tab_learn, tab_input = st.tabs(
    ["세계 금융 지도", "감시", "브리핑", "승인", "백테스트", "학습 층", "데이터 입력"])

# ---------- 0. 세계 금융 지도 ----------


@st.cache_data(show_spinner=False)
def map_exposure(snapshot: str) -> dict[str, float] | None:
    try:
        return geo.country_exposure(load_portfolio(), snapshot)
    except ExposureUnavailable:
        return None


@st.cache_data(show_spinner=False)
def map_impact(event_json: str, snapshot: str) -> dict[str, float] | None:
    try:
        return geo.country_impact(Event.model_validate_json(event_json), load_portfolio(), snapshot)
    except ExposureUnavailable:
        return None


with tab_map:
    st.subheader(f"금융 지도 · {LOCAL['name']} 중심" if is_local else "세계 금융 지도")
    live = mode == "라이브"
    b = current_briefing()
    map_event = (b.event if b else None) if live else events_by_id()[event_id]
    snapshot = "live" if live else event_id
    options = [v["label"] for v in geo.LAYERS.values()]
    shown = st.pills("표시", options, selection_mode="multi", default=options) or []
    uploaded = st.session_state.get("uploaded_portfolio")
    if uploaded is not None:  # 데이터 입력 탭에서 올린 실제 보유내역
        st.caption(f"포트폴리오: 업로드 ({uploaded.institution}, 노드 {len(uploaded.nodes)}개)")
        exp = geo.country_exposure(uploaded, snapshot)
        imp = geo.country_impact(map_event, uploaded, snapshot) if map_event else None
    else:
        exp = map_exposure(snapshot)
        imp = map_impact(map_event.model_dump_json(), snapshot) if map_event else None
    df, unmapped = geo.map_rows(
        event=map_event if geo.LAYERS["event"]["label"] in shown else None,
        exposure_by_country=exp if geo.LAYERS["exposure"]["label"] in shown else None,
        impact_by_country=imp if geo.LAYERS["impact"]["label"] in shown else None,
    )
    def scatter(k: str, v: dict) -> pdk.Layer:
        ring = k == "event"  # 사건은 빨간 테두리 원으로 그려 아래 원(비중·영향도)이 가려지지 않게
        return pdk.Layer("ScatterplotLayer", data=df[df["layer"] == v["label"]], get_position=["lon", "lat"],
                         get_radius="radius", get_fill_color="color", filled=not ring, stroked=True, pickable=True,
                         get_line_color=v["color"][:3] + [230] if ring else [255, 255, 255, 160],
                         line_width_min_pixels=3 if ring else 1, radius_min_pixels=3)

    layers = [scatter(k, v) for k, v in geo.LAYERS.items() if not df.empty and v["label"] in set(df["layer"])]
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=(
                                 pdk.ViewState(latitude=LOCAL["lat"], longitude=LOCAL["lon"], zoom=3.2) if is_local
                                 else pdk.ViewState(latitude=25, longitude=30, zoom=0.9)),
                             tooltip={"text": "{tooltip}"}), height=520)
    st.markdown(" · ".join(f":{c}[{m}] {geo.LAYERS[k]['label']}" for k, c, m in
                           [("event", "red", "○"), ("exposure", "blue", "●"), ("impact", "orange", "●")]))
    st.caption("원 크기: 사건(빨간 테두리) = 심각도, 보유 비중 = 국가별 노드 비중(프록시 펀드 보유 국가 반영, 거래상대방 포함), "
               "영향도 = 노출 경로 risk_score 합(비중×연관도×불확실성 감점, LLM 없이 규칙 매칭).")
    if map_event:
        st.markdown(f"**사건**: {map_event.title} ({map_event.date}) · 지역 {', '.join(map_event.regions)} · 심각도 {map_event.severity}/5")
    elif live:
        st.info("라이브 사건 브리핑이 없어 사건·영향도 원은 표시하지 않는다 (감시 탭에서 사건 탐지 시 생성).")
    if exp is None:
        st.warning(f"{snapshot} 시점 보유 스냅샷이 없어 보유 비중·영향도를 그릴 수 없다 (N-PORT 2019년 이전 미공개).")
    if is_local and not df.empty:
        loc = df[df["code"] == LOCAL["code"]].set_index("layer")["value"]
        m1, m2, m3 = st.columns(3)
        m1.metric(f"{LOCAL['name']} 보유 비중", f"{loc.get(geo.LAYERS['exposure']['label'], 0):.1%}")
        m2.metric(f"{LOCAL['name']} 영향도", f"{loc.get(geo.LAYERS['impact']['label'], 0):.4f}")
        m3.metric(f"{LOCAL['name']} 사건 지역", "예" if geo.LAYERS["event"]["label"] in loc.index else "아니오")
    g1, g2 = st.columns(2)
    chart(dashboard.country_chart(exp, "국가별 보유 비중 상위"), g1)
    chart(dashboard.country_chart(imp, "국가별 사건 영향도 상위", fmt=".3f"), g2)
    if not df.empty:
        top = (df.sort_values("value", ascending=False).groupby("layer").head(5)
               [["layer", "name", "code", "value"]].rename(columns={"layer": "레이어", "name": "국가", "code": "코드", "value": "값"}))
        st.dataframe(top, hide_index=True, width="stretch")
    if unmapped:
        st.caption("좌표로 표시하지 못한 지역(묶음·미상): " + "; ".join(f"{geo.LAYERS[k]['label']} {', '.join(v)}" for k, v in unmapped.items()))

# ---------- 1. 감시 ----------

with tab_watch:
    if is_local:
        st.subheader(f"{LOCAL['name']} 상시 감시")
        st.caption("GitHub Actions가 평일 30분마다 뉴스·DART 공시를, 하루 2회 ECOS 시장·외국인 순매수를 확인한다 (사전 등록 v5). "
                   "판단은 모두 원인 → 근거 → 결과로 남긴다.")
        loc = services.load_local_signals()
        if not loc:
            st.info("아직 로컬 감시 결과가 없다. 수집기가 처음 실행되면 표시된다.")
        else:
            lv = AlertLevel(loc["level"])
            summary_box(dashboard.watch_local(loc))
            th = load_config()["korea"]["thresholds"]
            g1, g2 = st.columns(2)
            chart(dashboard.z_chart((loc.get("kr_market") or {}).get("zscores"), th["market_z"], "한국 시장(A)"), g1)
            chart(dashboard.z_chart((loc.get("kr_flow") or {}).get("zscores"), th["flow_z"], "외국인 자금(C)"), g2)
            chart(dashboard.news_chart((loc.get("kr_news") or {}).get("observations"), load_config()["korea"]["news"]["z_threshold"],
                                       "한국 뉴스 주제별 기사 수 (최근 24시간)"))
            if loc.get("money_alert"):
                st.warning("1단계 자금 이상 알림 (한국 시장·외국인 자금)")
            for w in loc.get("warnings", []):
                (st.error if w["confirmed"] else st.warning)(
                    f"{'사건 확정' if w['confirmed'] else '사건 경고'}: {w['corp_name']} — {w['report_nm']} ({w['rcept_dt']}) · [공시 원문]({w['url']})")
            with st.expander("판단 근거 표 (원인 → 근거 → 결과)", expanded=lv == AlertLevel.ALERT):
                show_chain(loc["chain"])
            if lv != AlertLevel.ALERT:
                st.info("자동 대응안(알림)은 사건이 확인된 ALERT에서만 만든다. 지금 상황으로 브리핑을 보려면 "
                        "모드 '라이브' → 브리핑 탭 '▶ 지금 브리핑 실행'.")
            if loc.get("kr_news"):
                with st.expander("한국 뉴스 주제별 관측"):
                    obs = pd.DataFrame(loc["kr_news"]["observations"]).T.reset_index(names="주제")
                    st.dataframe(obs.astype(str), hide_index=True, width="stretch")
            if loc.get("notes"):
                st.caption("미설정·실패: " + "; ".join(loc["notes"]))
            reports = services.list_local_reports()
            if reports:
                with st.expander(f"대응안 리포트 {len(reports)}건"):
                    pick = st.selectbox("리포트", reports, format_func=lambda p: p.stem)
                    st.markdown(pick.read_text(encoding="utf-8"))
        st.divider()
        st.markdown("#### 글로벌 신호 (참고)")
    if mode == "백테스트 재생":
        e = events_by_id()[event_id]
        st.subheader(f"{e.title} 전후 경보 재생")
        st.caption("1단계 자금 이상 알림 = 시장 신호(A) 또는 자금 흐름(C). 2단계 대응안 = 사건 확정(B) + 1단계 → ALERT. 기준일까지 공개된 정보만 사용.")
        df = replay_signals(event_id)
        summary_box(dashboard.watch_replay(df, e.title, e.date))
        first_alert = df[df["등급"] == "ALERT"]["날짜"].min()
        c1, c2, c3 = st.columns(3)
        c1.metric("사건일", str(e.date))
        c2.metric("첫 ALERT", str(first_alert) if pd.notna(first_alert) else "없음")
        c3.metric("사건 전 자금 이상 알림일", int(((df["날짜"] < e.date) & df["자금 이상 알림"]).sum()))
        panel = market_panel()
        window = slice(pd.Timestamp(e.date - timedelta(days=60)), pd.Timestamp(e.date + timedelta(days=30)))
        cols = st.columns(2)
        for col, sid, label in [(cols[0], "VIXCLS", "VIX"), (cols[1], "BAA10Y" if e.date.year < 2024 else "BAMLH0A0HYM2", "신용스프레드")]:
            col.caption(f"{label} ({sid})")
            col.line_chart(panel[sid].loc[window])
        st.markdown("#### 판단 근거 (원인 → 근거 → 결과)")
        for name, chain in replay_chains(event_id).items():
            st.caption(name)
            show_chain(chain)
        with st.expander("일자별 재생 표"):
            st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.subheader("라이브 감시")
        st.caption("기본은 GitHub Actions 수집기가 3시간마다 모은 결과를 보여준다. '지금 직접 조회'는 FRED(병렬)와 "
                   "Google 뉴스 RSS(주제 8개, 키·요청 제한 없음)를 바로 부른다 (보통 10~20초, 1시간 캐시). "
                   "사건 신호는 주제별 최근 24시간 기사 수를 수집기가 3시간마다 쌓은 직전 30일 기준선과 비교한다 (기준점 20개, 약 2.5일 필요).")
        b1, b2 = st.columns(2)
        if b1.button("수집 결과 보기", type="primary"):
            st.session_state["signals"] = services.get_signals()
        if b2.button("지금 직접 조회"):
            with st.spinner("FRED·Google 뉴스 조회 중…"):
                st.session_state["signals"] = services.get_signals(refresh=True)
        sig = st.session_state.get("signals")
        if not sig:
            summary_box(dashboard.Summary("gray", "글로벌 신호 조회 전", [
                "'수집 결과 보기'는 3시간마다 모은 결과를 바로 보여준다",
                "'지금 직접 조회'는 FRED·Google 뉴스를 지금 부른다 (10~20초)"]))
        if sig:
            level = AlertLevel(sig["level"])
            news = sig["news"]
            status = news.get("status", "ok")
            src = "일일 수집기" if sig.get("source") == "collector" else "직접 조회"
            summary_box(dashboard.watch_global(sig))
            st.caption(f"출처: {src} · 조회 시각(UTC) {sig.get('collected_at', '-')}")
            scfg = load_config()["sentinel"]
            g1, g2 = st.columns(2)
            chart(dashboard.z_chart(sig["market"]["zscores"], scfg["market"]["z_threshold"], "시장(A)"), g1)
            chart(dashboard.z_chart((sig.get("flow") or {}).get("zscores"), scfg["flow"]["z_threshold"], "자금 흐름(C)"), g2)
            chart(dashboard.news_chart(news.get("observations"), scfg["news"]["z_threshold"], "글로벌 뉴스 주제별 기사 수 (최근 24시간)"))
            if sig.get("chain"):
                with st.expander("판단 근거 표 (원인 → 근거 → 결과)", expanded=level == AlertLevel.ALERT):
                    show_chain(sig["chain"])
            if status == "unavailable":
                st.error("사건 신호(B) 판단 불가: 뉴스 조회 실패 또는 기준선 축적 중이다. 등급의 '사건 없음'은 확인된 결과가 아니다.")
            if sig.get("money_alert"):
                st.warning("1단계 자금 이상 알림: 시장 또는 자금 흐름에서 이상이 감지됐다. 사건이 확정되면 대응안을 생성한다.")
            if sig.get("flow"):
                st.caption("자금 흐름(C): " + ", ".join(f"{k} {v:+.2f}" for k, v in sig["flow"]["zscores"].items()))
            c1, c2 = st.columns(2)
            c1.write("**시그널 A (시장)**")
            c1.dataframe(pd.DataFrame(sig["market"]["zscores"].items(), columns=["시리즈", "z-score"]), hide_index=True)
            c2.write("**시그널 B (뉴스)**")
            if news["clusters"]:
                c2.dataframe(pd.DataFrame(news["clusters"]), hide_index=True)
            elif status == "ok":
                c2.info("기사량 급증 군집 없음")
            elif status == "partial":
                c2.info(f"판단된 주제에서는 급증 군집 없음 (주제 {news.get('n_queries', '?')}개 중 {len(news['errors'])}개 판단 불가)")
            else:
                c2.error("판단 불가 (조회 실패 또는 기준선 축적 중)")
            if news.get("observations"):
                with c2.expander("주제별 관측 (Google 뉴스 최근 24시간)"):
                    st.dataframe(pd.DataFrame([{"주제": k, "기사": v["n_articles"], "언론사": v["n_sources"], "z": v["z"],
                                                "기준점": v["baseline_points"], "측정": v.get("measure", "-"),
                                                "키워드별 합산": v.get("n_split", "-"), "대표 기사": (v["top_titles"] or [""])[0][:60]}
                                               for k, v in news["observations"].items()]).astype(str),
                                 hide_index=True, width="stretch")
            if news["errors"]:
                with c2.expander(f"판단 불가 {len(news['errors'])}건 원인"):
                    for err in news["errors"]:
                        st.text(err)
            if sig["fred_error"]:
                st.warning(f"FRED 갱신 실패, 커밋된 캐시 사용: {sig['fred_error']}")
            if not news["clusters"]:
                st.caption("탐지된 사건이 없어 자동 브리핑은 만들지 않는다. 직접 보려면 브리핑 탭 '▶ 지금 브리핑 실행'.")
            if news["clusters"] and st.button("탐지 사건 브리핑 생성"):
                with st.spinner("에이전트 실행 중…"):
                    st.session_state["live_briefing"] = services.run_live(sig, **uploaded_args())

# ---------- 2. 브리핑 ----------

SCENARIO_NOTE = "가정 시나리오 — 사건은 사용자 입력이고 자동 감시 근거가 아니다"
TYPE_KO = {"banking_stress": "은행 위기", "liquidity_crisis": "유동성 위기", "credit_event": "신용 사건(부도)",
           "rate_shock": "금리 충격", "fx_shock": "환율 충격", "trade_policy": "무역·관세", "geopolitical": "지정학",
           "pandemic": "감염병", "supply_chain": "공급망", "regulatory": "규제", "other": "기타"}
DURATION_KO = {"shock": "단기 충격", "weeks": "수 주", "months": "수 개월", "structural": "구조적"}


def ondemand_panel() -> None:
    """감시 등급과 상관없이 지금 브리핑을 직접 실행 (현재 감시 신호 기준)."""
    sig = services.load_local_signals() if is_local else (st.session_state.get("signals") or services.get_signals())
    if not sig:
        st.warning("감시 신호가 아직 없다. 감시 탭에서 조회한 뒤 실행한다.")
        return
    topics, default, why = services.ondemand_topics(sig)
    with st.container(border=True):
        st.markdown(f"**▶ 지금 브리핑 실행** — {'대한민국' if is_local else '글로벌'} 감시 등급 "
                    f":{LEVEL_COLOR[AlertLevel(sig.get('level', 'NONE'))]}[{sig.get('level', 'NONE')}] · 사건 확인 여부와 상관없이 실행")
        if not topics:
            st.caption("뉴스 관측이 없어 주제를 고를 수 없다. 시나리오 브리핑을 쓴다.")
            return
        c1, c2 = st.columns([3, 1])
        topic = c1.selectbox("주제", topics, index=topics.index(default) if default in topics else 0,
                             format_func=lambda v: f"{TYPE_KO.get(v, v)} ({v})", key=f"od_topic_{market_view}")
        c1.caption(f"기본 선택: {why}")
        c2.write("")
        if c2.button("지금 브리핑 실행", type="primary", key="od_run"):
            event = services.ondemand_event(sig, topic, local=is_local)
            with st.spinner("에이전트 실행 중 (직접 실행)…"):
                st.session_state["live_briefing"] = services.run_ondemand(event, **uploaded_args())
            st.rerun()


def scenario_form(expanded: bool) -> None:
    """감시 등급과 무관하게 가정 사건으로 브리핑·노출·승인 단계를 쓴다 (자동 경보 원칙과 분리)."""
    from app.agents.matcher import RULE_CHANNELS
    from app.schemas import Channel, EventType

    with st.expander("🧪 시나리오 브리핑 (가정 사건 입력)", expanded=expanded):
        st.caption("자동 감시가 사건을 확인하지 않아도, 가정 사건을 직접 넣어 대응 문서 적합도·보유 노출·확인 항목을 본다. "
                   "결과에는 '가정 시나리오'로 표시되고 라이브 학습 기록(shadow_log)과 섞이지 않는다.")
        c1, c2 = st.columns(2)
        etype = c1.selectbox("사건 유형", [t.value for t in EventType], format_func=lambda v: f"{TYPE_KO.get(v, v)} ({v})",
                             key="sc_type")
        sev = c2.slider("심각도", 1, 5, 3, key="sc_sev", help="1 경미 ~ 5 시스템 위기")
        title = st.text_input("제목", placeholder="예: 국내 중형 증권사 PF 부실로 단기자금시장 경색", key="sc_title")
        desc = st.text_area("상황 설명", placeholder="무엇이 일어났고 어디로 번지는지 한두 줄", key="sc_desc", height=80)
        c3, c4 = st.columns(2)
        channels = c3.multiselect("전파 채널", [c.value for c in Channel], key=f"sc_ch_{etype}",
                                  default=[c.value for c in RULE_CHANNELS[EventType(etype)]])
        regions = c4.multiselect("지역", ["KR", "US", "CN", "JP", "EU", "RU", "UA", "EM", "GLOBAL"],
                                 default=["KR"] if is_local else ["GLOBAL"], key="sc_regions")
        c5, c6 = st.columns(2)
        duration = c5.selectbox("지속기간", list(DURATION_KO), index=1, format_func=DURATION_KO.get, key="sc_dur")
        entities = c6.text_input("관련 기관 (쉼표 구분, 선택)", placeholder="예: 태영건설, 한국투자증권", key="sc_ent",
                                 help="보유 종목 발행자와 규칙으로만 대조한다 (외부 LLM에 보유 종목명을 보내지 않음).")
        up = uploaded_args()
        if up:
            st.caption("업로드 데이터 반영: " + ", ".join(k for k in ("portfolio", "playbooks") if k in up))
        if st.button("시나리오 브리핑 생성", type="primary", disabled=not (title.strip() or desc.strip())):
            event = services.scenario_event(etype, desc, title=title, channels=channels, regions=regions, severity=sev,
                                            duration=duration, entities=[x.strip() for x in entities.split(",") if x.strip()])
            with st.spinner("에이전트 실행 중 (가정 시나리오)…"):
                st.session_state["live_briefing"] = services.run_scenario(event, **up)
            st.rerun()


def exposure_dot(b: Briefing) -> str:
    lines = ['digraph G { rankdir=LR; node [shape=box, style=rounded, fontsize=10];']
    edges = set()
    for p in b.exposure_entities + b.exposure_core + b.exposure_top:
        for a, c in zip(p.nodes, p.nodes[1:]):
            edges.add((a, c))
    lines += [f'"{a}" -> "{c}";' for a, c in sorted(edges)]
    return "\n".join(lines + ["}"])


with tab_brief:
    brief_summary = st.empty()  # 맨 위 요약 (컨트롤 실행 뒤 최종 브리핑으로 채움)
    b = current_briefing()
    if mode == "백테스트 재생":
        c1, c2 = st.columns([3, 1])
        c1.caption("커밋된 재생 결과를 표시한다. 다시 실행하면 캐시된 LLM 응답으로 같은 결과를 재현한다.")
        if c2.button("재생 다시 실행"):
            with st.spinner("에이전트 실행 중…"):
                st.session_state[f"briefing_{event_id}"] = b = services.run_replay(event_id)
    if mode == "백테스트 재생" and uploaded_args():
        up = uploaded_args()
        label = " + ".join(x for x in (f"포트폴리오 {up['portfolio'].institution}" if "portfolio" in up else "",
                                       f"문서 {len(st.session_state['uploaded_playbooks'])}개" if "playbooks" in up else "") if x)
        u1, u2 = st.columns([2, 1])
        if st.session_state.pop("_choose_upload", False):  # 위젯 생성 전에만 값을 바꿀 수 있다
            st.session_state["portfolio_choice"] = "업로드"
        u1.radio("포트폴리오", ["기본(합성)", "업로드"], horizontal=True, key="portfolio_choice",
                 help="업로드는 현재 보유·문서를 과거 사건에 적용한 가정 분석이다 (사건 당시와 다름).")
        if u2.button(f"업로드 데이터로 분석 ({label})"):
            with st.spinner("에이전트 실행 중 (업로드 데이터)…"):
                st.session_state[f"briefing_{event_id}_upload"] = services.run_replay(event_id, **uploaded_args())
                st.session_state["_choose_upload"] = True
            st.rerun()
        b = current_briefing()
    if mode == "라이브":
        ondemand_panel()
        scenario_form(expanded=False)
        b = current_briefing()
    if b is None:
        st.info("브리핑이 없다. 위 '지금 브리핑 실행'을 누르거나, 가정 사건은 '시나리오 브리핑'에 넣는다.")
    else:
        kind = services.briefing_kind(b)
        with brief_summary.container():
            summary_box(dashboard.briefing(b, kind=kind))
        synthetic_badge()
        if kind == "scenario":
            st.warning("🧪 " + SCENARIO_NOTE + ". 문서 적합도·노출·확인 항목은 이 가정 사건 기준이다.")
        elif kind == "ondemand":
            st.info("▶ 직접 실행 브리핑 — 자동 감시가 사건을 확인하지 않은 상태일 수 있다. 사건은 현재 감시 신호(뉴스 관측·시장 z)로 만들었다.")
        st.download_button("대응안 엑셀로 내보내기", data=export.briefing_xlsx(
            b, clause_text={k: c.text for k, c in all_clauses().items()}), file_name=f"alpha_sunset_{b.event.id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.markdown(f"## {b.event.title}  :{LEVEL_COLOR[b.alert_level]}[{b.alert_level.value}]")
        st.write(b.event.summary)
        st.caption(f"유형 {b.event.type.value} · 채널 {', '.join(c.value for c in b.event.channels)} · "
                   f"지역 {', '.join(b.event.regions)} · 심각도 {b.event.severity} · run {b.run_id}")

        st.markdown("### 문서별 적합도")
        if b.match.low_confidence:
            st.warning("판정 평균 신뢰도가 낮다 (low_confidence)")
        clauses = all_clauses()
        docs = docs_by_id() | {p.doc_id: p for p in st.session_state.get("uploaded_playbooks") or []}
        table = pd.DataFrame([{"순위": i, "문서": f.doc_id, "제목": docs[f.doc_id].title if f.doc_id in docs else "",
                               "fit_score": f.fit_score, "적용": f.n_applicable, "부분": f.n_partial,
                               "부적용": f.n_not, "불확실": f.n_uncertain}
                              for i, f in enumerate(b.match.doc_fits, start=1)])
        chart(dashboard.fit_chart(b.match.doc_fits))
        with st.expander("문서별 적합도 표"):
            st.dataframe(table, hide_index=True, width="stretch")
        for f in b.match.doc_fits[:5]:
            with st.expander(f"{f.doc_id} · {docs[f.doc_id].title if f.doc_id in docs else ''} (fit {f.fit_score:.2f})"):
                for j in f.judgments:
                    c = clauses.get(j.clause_id)
                    st.markdown(f"**{VERDICT_LABEL[j.verdict]} · {j.clause_id}**"
                                + (" 🔒" if c and c.protected else "") + f"  (신뢰도 {j.confidence:.2f})")
                    if c:
                        st.caption(c.text)
                    if j.evidence_quote:
                        st.markdown(f"> 근거: {j.evidence_quote}")
                    for r in j.mismatch_reasons:
                        st.markdown(f"- 불일치: {r}")

        st.markdown("### 공백 채널")
        st.write(", ".join(g.value for g in b.match.gaps) or "없음 — 사건 채널을 다루는 적용/부분적용 조항이 모두 있음")

        st.markdown("### 보유 자산 노출")
        if b.exposure_note:
            st.info(b.exposure_note)
        if b.exposure_entities:
            st.error("사건 기관과 같은 발행자를 보유: " + ", ".join(p.nodes[-2] for p in b.exposure_entities))
        if b.exposure_core:
            st.warning("핵심 경로 (사건 지역과 직접 겹치지만 비중이 작아 상위 10 밖): "
                       + " / ".join(" → ".join(p.nodes[1:]) for p in b.exposure_core))
        if b.exposure_top:
            chart(dashboard.exposure_chart(b.exposure_top))
            st.dataframe(pd.DataFrame([{"경로": " → ".join(p.nodes[1:]), "risk_score": p.risk_score, "비중": p.weight,
                                        "연관도": p.relevance, "불확실성": p.uncertainty, "이유": p.why}
                                       for p in b.exposure_top]), hide_index=True, width="stretch")
            st.graphviz_chart(exposure_dot(b))

        st.markdown("### 확인 항목 (담당별)")
        chart(dashboard.actions_chart(b.actions_to_check))
        grouped = defaultdict(list)
        for a in b.actions_to_check:
            role, _, rest = a.partition("] ")
            grouped[role.lstrip("[") if rest else "기타"].append(rest or a)
        cols = st.columns(min(3, max(1, len(grouped))))
        for i, (role, items) in enumerate(sorted(grouped.items())):
            with cols[i % len(cols)]:
                st.markdown(f"**{role}** ({len(items)})")
                for it in items:
                    st.markdown(f"- {it}")

        st.markdown("### 출처")
        for s in b.event.sources:
            st.markdown(f"- {s}")
        with st.expander("도구 호출 trace"):
            trace = services.get_trace(b.trace_id)
            st.dataframe(pd.DataFrame(trace) if trace else pd.DataFrame(), hide_index=True, width="stretch")

# ---------- 3. 승인 ----------

with tab_approve:
    b = current_briefing()
    if b is None:
        summary_box(dashboard.Summary("gray", "승인할 브리핑 없음", [
            "백테스트 재생 모드는 사건을 고르면 커밋된 브리핑이 뜬다",
            "라이브 모드는 감시 탭 사건 탐지 또는 브리핑 탭 시나리오 브리핑으로 만든다"]))
    else:
        summary_box(dashboard.approval(b, audit.read("app")))
        synthetic_badge()
        st.subheader(f"{b.event.title} — 문서 피드백")
        st.caption("피드백은 학습 층 입력(shadow_log)으로만 기록되며, 문서 우선순위 반영은 학습 층이 켜졌을 때만 한다.")
        for f in b.match.doc_fits[:6]:
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(f"**{f.doc_id}** {docs_by_id()[f.doc_id].title if f.doc_id in docs_by_id() else ''} (fit {f.fit_score:.2f})")
            for col, label, text in [(c2, "useful", "유용"), (c3, "not_fit", "부적합")]:
                if col.button(text, key=f"fb_{b.run_id}_{f.doc_id}_{label}"):
                    services.submit_feedback(Feedback(run_id=b.run_id, doc_id=f.doc_id, label=label, user_id=user_id), b)
                    st.toast(f"{f.doc_id}: {text} 기록")
        st.divider()
        note = st.text_input("승인 메모")
        c1, c2 = st.columns(2)
        if c1.button("브리핑 승인", type="primary"):
            services.record_approval(b, "approved", user_id, note)
            st.rerun()  # 맨 위 요약에 결정 반영
        if c2.button("반려"):
            services.record_approval(b, "rejected", user_id, note)
            st.rerun()

# ---------- 4. 백테스트 ----------

with tab_bt:
    res = services.get_backtest_results()
    g1, g2 = st.columns([3, 2])
    chart(dashboard.capture_chart(res.get("v6") or {}), g1)
    chart(dashboard.confusion_chart(((res.get("clause_eval") or {}).get("overall") or {}).get("confusion")), g2)
    chart(dashboard.lead_chart(res.get("v6") or {}))
    st.subheader("백테스트 결과")
    st.caption("실제 실행값만 표시한다. 정답 라벨 기반 지표(top3 적중, P/R)는 라벨 작성 후 P8에서 산출한다.")
    if is_local and res.get("kr"):
        kr = res["kr"]
        st.markdown(f"**{LOCAL['name']} 신호 백테스트** (사전 등록 v5, `data/backtest/kr_results.json`)")
        ks = kr["summary"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("사건 전 알림 선행일", f"{ks['kr_warning_lead_days']}일")
        c2.metric("사건 → 대응안", f"{ks['kr_briefing_delay_days']}일")
        c3.metric("평상시 알림 비율", f"{ks['kr_calm_money_alert_rate']:.2%}")
        c4.metric("사전 알림 사건 / 기준선", f"{ks['kr_events_with_prior_warning']:.0%} / {ks['kr_base_rate']:.0%}")
        st.dataframe(pd.DataFrame([{
            "사건": r["event_id"], "첫 자금 이상 알림": r["first_kr_money_alert"], "선행일": r["kr_warning_lead_days"],
            "원인(알림)": ", ".join(f"{k} z={v:+.2f}" for k, v in r["kr_money_alert_cause"].items()),
            "첫 대응안": r["first_kr_alert"], "지연": r["kr_briefing_delay_days"],
            "원인(대응안)": ", ".join(f"{k} z={v:+.2f}" for k, v in r["kr_alert_cause"].items()),
            "글로벌 선행일": r["global_warning_lead_days"]} for r in kr["events"]]).astype(str), hide_index=True, width="stretch")
        for note in kr["notes"]:
            st.caption(note)
        st.divider()
    if res["backtest"]:
        bt = res["backtest"]
        st.markdown("**지표 요약** (`data/backtest_results.json`)")
        if bt["unlabeled_events"]:
            st.info("라벨 미작성 사건: " + ", ".join(bt["unlabeled_events"]) + " — 해당 사건의 라벨 기반 지표는 비어 있다.")
        st.dataframe(pd.DataFrame([bt["summary"]]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(bt["events"]), hide_index=True, width="stretch")
        rc = bt["false_alarms"]["random_calm"]
        st.markdown(f"**무작위 평상 구간**: 영업일 {rc['n_days']}일 중 시그널 A 단독 발동률 {rc['market_active_rate']:.2%}")
        st.dataframe(pd.DataFrame(rc["quarters"]), hide_index=True, width="stretch")
        st.caption(rc["note"])
    if res["sentinel"]:
        st.markdown("**Sentinel 경보 재현**")
        st.dataframe(pd.DataFrame(res["sentinel"]["events"]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(res["sentinel"]["calm"]), hide_index=True, width="stretch")
        st.caption(res["sentinel"]["note"])
    if res["match"]:
        st.markdown("**Matcher 판정**")
        st.dataframe(pd.DataFrame([{**{k: v for k, v in r.items() if k not in ("verdicts", "card_check", "top3")},
                                    **r["verdicts"], "top3": ", ".join(f"{d}({s:.2f})" for d, s in r["top3"])}
                                   for r in res["match"]]), hide_index=True, width="stretch")
    if res["exposure"]:
        st.markdown("**Exposure 상위 경로 (1위)**")
        st.dataframe(pd.DataFrame([{"사건": k, "불확실 비율": v["uncertain_ratio"],
                                    "1위 경로": " → ".join(v["paths"][0]["nodes"][1:]) if v["paths"] else "",
                                    "동일 발행자": ", ".join(p["nodes"][3] for p in v.get("entity_paths", []))}
                                   for k, v in res["exposure"].items()]), hide_index=True, width="stretch")

# ---------- 5. 학습 층 ----------

with tab_learn:
    learn_summary = st.empty()
    st.subheader("학습 층 (알파 썬셋)")
    st.caption("자주 유용했던 문서의 검색 우선순위를 올리고 거의 쓰이지 않는 문서는 내린다. 문서는 삭제·폐기하지 않는다. "
               "protected 문서는 우선순위 하한 0.5로 항상 후보에 남는다. 기본 OFF.")
    current = services.learner_enabled()
    enabled = st.toggle("학습 층 ON", value=current,
                        help="ON이면 브리핑의 문서 순위에 final = fit × (1 + 0.3·(priority − 0.5))를 적용한다.")
    if enabled != current:
        services.set_learner_enabled(enabled)
        st.toast(f"학습 층 {'ON' if enabled else 'OFF'} (변경 이력 기록)")
    res = services.get_backtest_results()
    lr = res.get("learner")
    pr = services.get_priority()
    with learn_summary.container():
        summary_box(dashboard.learner(enabled, pr["docs"], lr["pass_B"]["learner_delta_sim"] if lr else None))
    chart(dashboard.priority_chart(pr["docs"]))
    if lr:
        st.markdown("**ON/OFF 비교 (시뮬레이션 기반, 사전 등록 v4)**")
        c1, c2 = st.columns(2)
        c1.metric("실제 순서 1회 재생 delta", lr["pass_A"]["learner_delta"],
                  help=f"OFF {lr['pass_A']['doc_top3_hit_off']} / ON {lr['pass_A']['doc_top3_hit_on']}")
        c2.metric("반복 2회차 delta", lr["pass_B"]["learner_delta_sim"],
                  help=f"OFF {lr['pass_B']['doc_top3_hit_off']} / ON {lr['pass_B']['doc_top3_hit_on']}")
        sim = pd.DataFrame(lr["pass_B"]["events"])[["event_id", "as_of", "top3_off", "top3_on", "hit_off", "hit_on", "priority_top"]]
        # [문서, 점수] 쌍 목록은 Arrow 직렬화가 안 되므로 문자열로 표시
        sim["priority_top"] = sim["priority_top"].map(lambda xs: ", ".join(f"{d}({p:.2f})" for d, p in xs))
        for col in ("top3_off", "top3_on"):
            sim[col] = sim[col].map(", ".join)
        st.dataframe(sim,
                     hide_index=True, width="stretch")
        for c in lr["caveats"]:
            st.caption("⚠️ " + c)
    st.markdown("**인용·피드백 기록 (shadow_log, 백테스트·승인 탭 피드백)**")
    if pr["docs"]:
        st.dataframe(pd.DataFrame(pr["docs"]), hide_index=True, width="stretch")
    else:
        st.info("아직 기록된 인용·피드백이 없다.")

# ---------- 7. 데이터 입력 ----------

with tab_approve:
    st.divider()
    st.subheader("감사 로그 (추가 전용 · 해시 체인)")
    st.caption("승인·피드백·브리핑 생성·업로드·학습 층 토글·자동 알림을 한 줄씩 남긴다. 줄마다 앞 줄 해시를 품고 있어 "
               "중간 줄을 고치거나 지우면 검증이 깨진다. 업로드는 파일 이름·내용 대신 해시와 건수만 남긴다. "
               "자동 감시(collect_signals·monitor_kr) 기록은 저장소에 커밋되고, 앱 기록(app)은 이 서버에만 남으니 내려받아 보관한다.")
    srcs = audit.sources()
    if not srcs:
        st.info("아직 기록이 없다.")
    for s in srcs:
        v = audit.verify(s)
        rows = audit.read(s)
        c1, c2, c3 = st.columns([2, 3, 2])
        c1.markdown(f"**{s}** · {v.n}줄")
        if v.ok:
            c2.success("체인 검증 통과" + (f" · 마지막 해시 `{rows[-1]['hash'][:12]}…`" if rows else ""))
        else:
            c2.error(f"검증 실패 (seq {v.bad_seq}): {v.reason}")
        c3.download_button("JSONL 받기", data=audit.path_for(s).read_bytes(), file_name=f"audit_{s}.jsonl",
                           mime="application/json", key=f"audit_dl_{s}")
        if rows:
            st.dataframe(pd.DataFrame([{"seq": r["seq"], "ts": r["ts"], "action": r["action"], "actor": r["actor"],
                                        "data": json.dumps(r["data"], ensure_ascii=False)[:200]} for r in rows[-50:][::-1]]),
                         hide_index=True, width="stretch")

with tab_input:
    from app.ingest.mapper import ColumnMap, MappingSpec
    from app.ingest.pipeline import ingest, pick_sheet, propose
    from app.ingest.profile import profile_text
    from app.ingest.reader import read_file
    from app.ingest.schema import FIELDS
    from app.ingest.transform import apply_spec, save_preset, to_portfolio

    summary_box(dashboard.data_input(st.session_state.get("uploaded_portfolio"), st.session_state.get("uploaded_holdings"),
                                     st.session_state.get("uploaded_playbooks")))
    if st.session_state.get("uploaded_holdings"):
        held = pd.DataFrame(st.session_state["uploaded_holdings"])
        g1, g2 = st.columns(2)
        chart(dashboard.weight_chart(held, "sector", "반영 중 포트폴리오 · 업종 비중"), g1)
        chart(dashboard.weight_chart(held, "country", "반영 중 포트폴리오 · 국가 비중"), g2)
    st.subheader("보유내역 입력 (엑셀·CSV → 공통 스키마)")
    st.caption("파일 모양이 달라도 된다. 라이브러리가 표 구조를 읽어 글로 요약하고, LLM은 그 요약만 보고 열 매핑 규칙을 제안한다. "
               "숫자 변환·검증은 코드가 전체 행에 적용한다. 같은 양식은 저장해 두면 다음부터 LLM 없이 변환한다.")
    st.caption("공통 스키마는 SEC N-PORT 보유 항목과 ISO 표준(ISIN 6166 · 국가 3166 · 통화 4217)에 맞춘 내부 표준이다.")
    up = st.file_uploader("보유내역 파일", type=["xlsx", "xlsm", "csv"])
    samples = sorted(p.name for p in (Path(__file__).resolve().parent.parent / "data" / "ingest" / "samples").glob("*.*")
                     if p.suffix in (".xlsx", ".csv"))
    sample = st.selectbox("또는 예시 파일", ["(선택 안 함)"] + samples)
    use_llm = st.toggle("LLM 매핑 제안 사용 (헤더·샘플 요약만 전송)", value=False)
    src = name = None
    if up is not None:
        src, name = up.getvalue(), up.name
    elif sample != "(선택 안 함)":
        path = Path(__file__).resolve().parent.parent / "data" / "ingest" / "samples" / sample
        src, name = path.read_bytes(), sample
    if src is not None:
        sheets = read_file(src, name)
        sheet, prof = pick_sheet(sheets)
        with st.expander("① 표 구조 요약 (LLM에 보내는 글)"):
            st.code(profile_text(prof), language=None)
        key = f"spec_{name}_{use_llm}"
        if key not in st.session_state:
            llm = None
            if use_llm:
                from app.llm.client import LLMClient

                llm = LLMClient(db_mode="sandbox")
            with st.spinner("매핑 규칙 만드는 중…"):
                st.session_state[key] = propose(sheet, prof, llm)
        spec: MappingSpec = st.session_state[key]
        st.markdown(f"**② 열 매핑 제안** (방식: {spec.method}, 헤더 {spec.header_row}행) — 표에서 바로 고칠 수 있다")
        edited = st.data_editor(pd.DataFrame([c.model_dump() for c in spec.columns]), num_rows="dynamic", hide_index=True,
                                width="stretch", column_config={
                                    "field": st.column_config.SelectboxColumn("필드", options=list(FIELDS)),
                                    "source": st.column_config.SelectboxColumn("원본 열", options=prof.headers),
                                    "multiplier": st.column_config.NumberColumn("금액 단위 배수"),
                                    "percent": st.column_config.CheckboxColumn("% → ÷100"),
                                    "reason": st.column_config.TextColumn("근거", width="large")})
        if spec.defaults:
            st.caption("기본값: " + "; ".join(f"{k}={v} ({spec.default_reasons.get(k, '')})" for k, v in spec.defaults.items()))
        for n in spec.notes:
            st.warning(n)
        spec = spec.model_copy(update={"columns": [ColumnMap(**{k: v for k, v in r.items() if pd.notna(v) or k == "reason"})
                                                    for r in edited.to_dict("records") if r.get("field") and r.get("source")]})
        res = apply_spec(sheet, prof, spec)
        st.markdown("**③ 변환 결과와 검증 (원인 → 근거 → 결과)**")
        show_chain(res.chain)
        g1, g2 = st.columns(2)
        chart(dashboard.weight_chart(res.holdings, "sector", "변환 결과 · 업종 비중"), g1)
        chart(dashboard.weight_chart(res.holdings, "country", "변환 결과 · 국가 비중"), g2)
        st.dataframe(res.holdings.head(200).round({"weight": 6}).astype(str), hide_index=True, width="stretch")
        if res.dropped:
            st.caption(f"제외 {len(res.dropped)}행: " + "; ".join(f"{d['row']}행 {d['reason']}" for d in res.dropped[:5]))
        c1, c2, c3 = st.columns(3)
        c1.download_button("공통 스키마 엑셀 받기", data=export.holdings_xlsx(res.holdings, res.chain),
                           file_name="holdings_standard.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c2.button("이 양식 저장 (다음부터 LLM 없이)"):
            st.success(f"저장: {save_preset(prof, spec, name).name}")
        if c3.button("이 포트폴리오로 분석", type="primary", disabled=res.holdings.empty):
            st.session_state["uploaded_portfolio"] = to_portfolio(res.holdings, institution=name)
            st.session_state["uploaded_holdings"] = res.holdings[["name", "isin", "weight", "country", "sector", "source_row"]] \
                .astype(object).where(res.holdings.notna(), None).to_dict("records")
            audit.log("upload_portfolio", {"file_sha256": audit.sha256_bytes(src), "rows": int(len(res.holdings)),
                                           "dropped": len(res.dropped), "mapping": spec.method, "llm": use_llm}, actor=user_id)
            st.success("세계 금융 지도와 브리핑(가정 분석·라이브)에 업로드 포트폴리오를 반영했다.")
    if st.session_state.get("uploaded_portfolio") is not None and st.button("업로드 포트폴리오 해제"):
        del st.session_state["uploaded_portfolio"]

    # ---------- 대응 문서 입력 ----------
    st.divider()
    st.subheader("대응 문서 입력 (PDF·워드·텍스트 → 조항)")
    st.caption("문서를 조항으로 나누고(번호·조문 패턴, 원문 그대로), LLM은 조항마다 전제 사건·채널·조치·담당만 채운다. "
               "담당은 원문에 적힌 부서명만, 법규·보험 보호는 원문 인용 근거가 있을 때만 인정한다. LLM을 끄면 규칙만으로 분해한다.")
    from app.ingest.documents import ingest_document

    doc_files = st.file_uploader("대응 문서", type=["pdf", "docx", "txt", "md"], accept_multiple_files=True)
    doc_dir = Path(__file__).resolve().parent.parent / "data" / "ingest" / "doc_samples"
    doc_samples = sorted(p.name for p in doc_dir.glob("*.*") if p.suffix in (".pdf", ".docx"))
    doc_pick = st.multiselect("또는 예시 문서", doc_samples)
    doc_llm = st.toggle("LLM 속성 채우기 사용 (조항 원문 전송)", value=False, key="doc_llm")
    docs = [(f.getvalue(), f.name) for f in doc_files or []] + [((doc_dir / n).read_bytes(), n) for n in doc_pick]
    if docs:
        llm = None
        if doc_llm:
            from app.llm.client import LLMClient

            llm = LLMClient(db_mode="sandbox")
        results = []
        for data, name in docs:
            key = f"doc_{name}_{len(data)}_{doc_llm}"
            if key not in st.session_state:
                with st.spinner(f"{name} 변환 중…"):
                    st.session_state[key] = ingest_document(data, name, llm=llm)
            results.append(st.session_state[key])
        for r in results:
            st.markdown(f"**{r.playbook.title}** (`{r.playbook.doc_id}`, 조항 {len(r.playbook.clauses)}개)")
            show_chain(r.chain)
            st.dataframe(pd.DataFrame(r.rows).astype(str), hide_index=True, width="stretch")
            st.download_button(f"{r.playbook.doc_id} 플레이북 JSON 받기", data=r.playbook.model_dump_json(indent=2),
                               file_name=f"{r.playbook.doc_id}.json", mime="application/json", key=f"dl_{r.playbook.doc_id}")
        d1, d2 = st.columns(2)
        d1.radio("분석에 쓸 문서", ["업로드 문서만", "기본 문서와 함께"], horizontal=True, key="doc_mode")
        if d2.button("이 문서로 분석", type="primary", disabled=not any(r.playbook.clauses for r in results)):
            st.session_state["uploaded_playbooks"] = [r.playbook for r in results if r.playbook.clauses]
            audit.log("upload_documents", {"docs": [{"file_sha256": audit.sha256_bytes(d), "doc_id": r.playbook.doc_id,
                                                     "clauses": len(r.playbook.clauses)} for (d, _), r in zip(docs, results)],
                                           "mode": st.session_state.get("doc_mode"), "llm": doc_llm}, actor=user_id)
            st.success("브리핑(가정 분석·라이브)에 업로드 문서를 반영했다. 브리핑 탭에서 '업로드 데이터로 분석'을 누른다.")
    if st.session_state.get("uploaded_playbooks") and st.button("업로드 문서 해제"):
        del st.session_state["uploaded_playbooks"]
