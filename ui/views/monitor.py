"""감시 — 시장(A)·자금(C)·사건(B) 신호와 등급. 백테스트 재생은 사건 전후 재생."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from app import dashboard, services
from app.schemas import AlertLevel
from ui import common as ui

LOCAL = ui.local_market()
cfg = ui.cfg()

ui.page_header("감시", "시장·자금 흐름 이상(1단계 알림)과 사건 확정(2단계 대응안)을 판단한다. "
               "모든 판단은 원인 → 근거 → 결과로 남는다.", eyebrow="운영 · 01")


def local_section() -> None:
    loc = services.load_local_signals()
    ui.section(f"{LOCAL['name']} 상시 감시", "GitHub Actions · 평일 30분마다 뉴스·DART, 하루 2회 ECOS")
    if not loc:
        ui.empty_state("로컬 감시 결과 없음", "수집기가 처음 실행되면 이곳에 표시된다.")
        return
    lv = AlertLevel(loc["level"])
    ui.summary_box(dashboard.watch_local(loc))
    for w in loc.get("warnings", []):
        (st.error if w["confirmed"] else st.warning)(
            f"{'사건 확정' if w['confirmed'] else '사건 경고'} · {w['corp_name']} — {w['report_nm']} ({w['rcept_dt']}) · "
            f"[공시 원문]({w['url']})", icon=":material/gavel:")
    th = cfg["korea"]["thresholds"]
    g1, g2 = st.columns(2)
    ui.chart(dashboard.z_chart((loc.get("kr_market") or {}).get("zscores"), th["market_z"], "한국 시장(A)"), g1)
    ui.chart(dashboard.z_chart((loc.get("kr_flow") or {}).get("zscores"), th["flow_z"], "외국인 자금(C)"), g2)
    ui.chart(dashboard.news_chart((loc.get("kr_news") or {}).get("observations"), cfg["korea"]["news"]["z_threshold"],
                                  "한국 뉴스 주제별 기사 수 (최근 24시간)"))
    with st.expander("판단 근거 (원인 → 근거 → 결과)", expanded=lv == AlertLevel.ALERT, icon=":material/account_tree:"):
        ui.show_chain(loc["chain"])
    if lv != AlertLevel.ALERT:
        st.caption("자동 대응안(알림)은 사건이 확인된 ALERT에서만 만든다. 지금 상황으로 브리핑을 보려면 "
                   "모드를 '라이브'로 바꾸고 브리핑 › 지금 브리핑 실행.")
    if loc.get("kr_news"):
        with st.expander("한국 뉴스 주제별 관측", icon=":material/table_rows:"):
            obs = pd.DataFrame(loc["kr_news"]["observations"]).T.reset_index(names="주제")
            st.dataframe(obs.astype(str), hide_index=True, width="stretch")
    reports = services.list_local_reports()
    if reports:
        with st.expander(f"대응안 리포트 {len(reports)}건", icon=":material/article:"):
            pick = st.selectbox("리포트", reports, format_func=lambda p: p.stem)
            st.markdown(pick.read_text(encoding="utf-8"))
    if loc.get("notes"):
        st.caption("미설정·실패: " + "; ".join(loc["notes"]))


def replay_section() -> None:
    e = ui.events_by_id()[ui.event_id()]
    ui.section(f"{e.title} — 전후 경보 재생", "기준일까지 공개된 정보만 사용")
    df = ui.replay_signals(ui.event_id())
    ui.summary_box(dashboard.watch_replay(df, e.title, e.date))
    first_alert = df[df["등급"] == "ALERT"]["날짜"].min()
    money = df[(df["날짜"] < e.date) & df["자금 이상 알림"]]["날짜"]
    c1, c2, c3 = st.columns(3)
    c1.metric("사건일", str(e.date), border=True)
    c2.metric("첫 ALERT", str(first_alert) if pd.notna(first_alert) else "없음", border=True,
              help="2단계 대응안 = 사건 확정(B) ∧ 1단계 알림")
    c3.metric("사건 전 자금 이상 알림", f"{len(money)}일", border=True,
              delta=f"첫 알림 {(e.date - money.min()).days}일 전" if len(money) else None, delta_color="off", delta_arrow="off",
              help="1단계 = 시장 신호(A) 또는 자금 흐름(C)")
    panel = ui.market_panel()
    window = slice(pd.Timestamp(e.date - timedelta(days=60)), pd.Timestamp(e.date + timedelta(days=30)))
    cols = st.columns(2)
    for col, sid, label in [(cols[0], "VIXCLS", "VIX"),
                            (cols[1], "BAA10Y" if e.date.year < 2024 else "BAMLH0A0HYM2", "신용스프레드")]:
        with col.container(border=True, key=f"line-{sid}"):
            st.caption(f"{label} · {sid} · 사건일 전 60일 ~ 후 30일")
            st.line_chart(panel[sid].loc[window], height=220, color="#1f4e89")
    ui.section("판단 근거", "원인 → 근거 → 결과")
    for name, chain in ui.replay_chains(ui.event_id()).items():
        st.caption(name)
        ui.show_chain(chain)
    with st.expander("일자별 재생 표", icon=":material/table_rows:"):
        st.dataframe(df, hide_index=True, width="stretch")


def global_live_section() -> None:
    ui.section("글로벌 라이브 감시", "기본 = 수집기 결과(3시간 주기) · 직접 조회 = FRED + Google 뉴스 RSS")
    b1, b2, _ = st.columns([1, 1, 3])
    if b1.button("수집 결과 보기", type="primary", icon=":material/inventory_2:", width="stretch"):
        st.session_state["signals"] = services.get_signals()
    if b2.button("지금 직접 조회", icon=":material/refresh:", width="stretch",
                 help="FRED(병렬)와 Google 뉴스 RSS 주제 8개를 지금 부른다 (보통 10~20초)."):
        with st.spinner("FRED·Google 뉴스 조회 중…"):
            st.session_state["signals"] = services.get_signals(refresh=True)
    sig = st.session_state.get("signals")
    if not sig:
        ui.summary_box(dashboard.Summary("gray", "글로벌 신호 조회 전", [
            "**수집 결과 보기** — 3시간마다 모은 결과를 바로 보여준다",
            "**지금 직접 조회** — FRED·Google 뉴스를 지금 부른다 (10~20초)",
            "사건 신호는 주제별 최근 24시간 기사 수를 직전 30일 기준선과 비교한다 (기준점 20개, 약 2.5일 필요)"]))
        return
    level = AlertLevel(sig["level"])
    news = sig["news"]
    status = news.get("status", "ok")
    ui.summary_box(dashboard.watch_global(sig))
    st.caption(f"출처 {'일일 수집기' if sig.get('source') == 'collector' else '직접 조회'} · "
               f"조회 시각(UTC) {sig.get('collected_at', '-')}")
    if status == "unavailable":
        st.error("사건 신호(B) 판단 불가: 뉴스 조회 실패 또는 기준선 축적 중이다. 등급의 '사건 없음'은 확인된 결과가 아니다.",
                 icon=":material/help:")
    if sig.get("money_alert"):
        st.warning("1단계 자금 이상 알림: 시장 또는 자금 흐름에서 이상이 감지됐다. 사건이 확정되면 대응안을 생성한다.",
                   icon=":material/trending_down:")
    if sig.get("fred_error"):
        st.warning(f"FRED 갱신 실패, 커밋된 캐시 사용: {sig['fred_error']}", icon=":material/cloud_off:")
    scfg = cfg["sentinel"]
    g1, g2 = st.columns(2)
    ui.chart(dashboard.z_chart(sig["market"]["zscores"], scfg["market"]["z_threshold"], "시장(A)"), g1)
    ui.chart(dashboard.z_chart((sig.get("flow") or {}).get("zscores"), scfg["flow"]["z_threshold"], "자금 흐름(C)"), g2)
    ui.chart(dashboard.news_chart(news.get("observations"), scfg["news"]["z_threshold"], "글로벌 뉴스 주제별 기사 수 (최근 24시간)"))

    if news["clusters"]:
        ui.section("탐지된 사건 군집")
        st.dataframe(pd.DataFrame(news["clusters"]).astype(str), hide_index=True, width="stretch")
        if st.button("탐지 사건 브리핑 생성", type="primary", icon=":material/play_arrow:"):
            with st.spinner("에이전트 실행 중…"):
                st.session_state["live_briefing"] = services.run_live(sig, **ui.uploaded_args())
            st.switch_page(ui.PAGE_BRIEFING)
    elif status == "ok":
        st.caption("기사량 급증 군집 없음 — 자동 브리핑은 만들지 않는다. 직접 보려면 브리핑 › 지금 브리핑 실행.")
    elif status == "partial":
        st.caption(f"판단된 주제에서는 급증 군집 없음 (주제 {news.get('n_queries', '?')}개 중 {len(news['errors'])}개 판단 불가).")

    if sig.get("chain"):
        with st.expander("판단 근거 (원인 → 근거 → 결과)", expanded=level == AlertLevel.ALERT, icon=":material/account_tree:"):
            ui.show_chain(sig["chain"])
    with st.expander("신호 원자료", icon=":material/table_rows:"):
        c1, c2 = st.columns(2)
        c1.caption("시그널 A · 시장 z-score")
        c1.dataframe(pd.DataFrame(sig["market"]["zscores"].items(), columns=["시리즈", "z-score"]), hide_index=True,
                     width="stretch")
        if sig.get("flow"):
            c2.caption("시그널 C · 자금 흐름 z-score")
            c2.dataframe(pd.DataFrame(sig["flow"]["zscores"].items(), columns=["시리즈", "z-score"]), hide_index=True,
                         width="stretch")
        if news.get("observations"):
            st.caption("시그널 B · 주제별 관측 (Google 뉴스 최근 24시간)")
            st.dataframe(pd.DataFrame([{"주제": k, "기사": v["n_articles"], "언론사": v["n_sources"], "z": v["z"],
                                        "기준점": v["baseline_points"], "측정": v.get("measure", "-"),
                                        "키워드별 합산": v.get("n_split", "-"), "대표 기사": (v["top_titles"] or [""])[0][:60]}
                                       for k, v in news["observations"].items()]).astype(str),
                         hide_index=True, width="stretch")
        if news["errors"]:
            st.caption(f"판단 불가 {len(news['errors'])}건 원인")
            st.code("\n".join(news["errors"]), language=None)


if ui.is_local():
    local_section()
if ui.is_live():
    if not ui.is_local():
        global_live_section()
    else:
        with st.expander("글로벌 신호 (참고)", icon=":material/language:"):
            global_live_section()
else:
    replay_section()
