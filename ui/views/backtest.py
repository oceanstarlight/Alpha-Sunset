"""백테스트 — 사건 포착률 vs 우연, 선행일, 조항 판정 정확도, 단계별 재현 결과."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import dashboard
from ui import common as ui

LOCAL = ui.local_market()
res = ui.backtest_results()
v6 = res.get("v6") or {}

ui.page_header("백테스트", "커밋된 실제 실행값만 보여준다. 임계치·가중치는 라벨로 튜닝하지 않고, 규칙과 정답은 "
               "실행 전에 사전 등록으로 고정했다.", eyebrow="분석 · 05")

# ---------- 핵심 지표 ----------
g = (v6.get("global") or {}).get("adopted_full_period") or (v6.get("global") or {}).get("current_full_period")
k = (v6.get("local_kr") or {}).get("current_full_period")
ce = ((res.get("clause_eval") or {}).get("overall") or {})
if g:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("글로벌 사건 포착", f"{g['caught']}/{g['n_events']}", border=True,
              delta=f"우연 {g['base_rate_caught']:.0%} · p={g['p_value_caught']:.4f}", delta_color="off", delta_arrow="off",
              help="같은 규칙으로 무작위 날짜를 찍었을 때 포착될 비율과 비교한다 (사전 등록 v6).")
    c2.metric("평균 선행일", f"{g['mean_lead_days']:.1f}일", border=True,
              delta=f"사전 알림 {g['prior_warning']}건", delta_color="off", delta_arrow="off")
    c3.metric("평상시 알림 비율", f"{g['calm_alert_rate']:.1%}", border=True,
              delta=f"평상 영업일 {g['n_calm_days']:,}일", delta_color="off", delta_arrow="off", help="알림 피로도")
    if ce:
        c4.metric("조항 판정 일치도 (κ)", f"{ce['kappa']:.2f}", border=True,
                  delta=f"정확도 {ce['accuracy']:.2f}", delta_color="off", delta_arrow="off",
                  help="격리 라벨러의 6사건 × 96조항 전수 라벨 대비 (사전 등록 v7).")
if k and ui.is_local():
    st.caption(f"{LOCAL['name']} 로컬 신호: 포착 {k['caught']}/{k['n_events']} vs 우연 {k['base_rate_caught']:.0%} "
               f"(p={k['p_value_caught']:.2f}) — 우연과 구분되지 않아 한계로 보고한다.")

g1, g2 = st.columns([3, 2])
ui.chart(dashboard.capture_chart(v6), g1)
ui.chart(dashboard.confusion_chart(ce.get("confusion")), g2)
ui.chart(dashboard.lead_chart(v6))

tabs = ["단계별 지표", "경보 재현", "판정 · 노출"] + ([f"{LOCAL['name']} 신호"] if res.get("kr") else [])
t = st.tabs(tabs)

with t[0]:
    bt = res.get("backtest")
    if not bt:
        st.caption("결과 파일 없음 (data/backtest_results.json)")
    else:
        if bt["unlabeled_events"]:
            st.info("라벨 미작성 사건: " + ", ".join(bt["unlabeled_events"]) + " — 해당 사건의 라벨 기반 지표는 비어 있다.")
        st.caption("지표 요약 · data/backtest_results.json")
        st.dataframe(pd.DataFrame([bt["summary"]]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(bt["events"]), hide_index=True, width="stretch")
        rc = bt["false_alarms"]["random_calm"]
        st.markdown(f"**무작위 평상 구간** :gray[영업일 {rc['n_days']}일 중 시그널 A 단독 발동률 {rc['market_active_rate']:.2%}]")
        st.dataframe(pd.DataFrame(rc["quarters"]), hide_index=True, width="stretch")
        st.caption(rc["note"])

with t[1]:
    if res.get("sentinel"):
        st.markdown("**Sentinel 경보 재현** :gray[사건 6개 · 평상 3구간]")
        st.dataframe(pd.DataFrame(res["sentinel"]["events"]), hide_index=True, width="stretch")
        st.dataframe(pd.DataFrame(res["sentinel"]["calm"]), hide_index=True, width="stretch")
        st.caption(res["sentinel"]["note"])

with t[2]:
    if res.get("match"):
        st.markdown("**Matcher 판정**")
        st.dataframe(pd.DataFrame([{**{k_: v for k_, v in r.items() if k_ not in ("verdicts", "card_check", "top3")},
                                    **r["verdicts"], "top3": ", ".join(f"{d}({s:.2f})" for d, s in r["top3"])}
                                   for r in res["match"]]), hide_index=True, width="stretch")
    if res.get("exposure"):
        st.markdown("**Exposure 상위 경로 (1위)**")
        st.dataframe(pd.DataFrame([{"사건": k_, "불확실 비율": v["uncertain_ratio"],
                                    "1위 경로": " → ".join(v["paths"][0]["nodes"][1:]) if v["paths"] else "",
                                    "동일 발행자": ", ".join(p["nodes"][3] for p in v.get("entity_paths", []))}
                                   for k_, v in res["exposure"].items()]), hide_index=True, width="stretch")

if res.get("kr"):
    with t[3]:
        kr = res["kr"]
        ks = kr["summary"]
        st.caption("사전 등록 v5 · data/backtest/kr_results.json")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("사건 전 알림 선행일", f"{ks['kr_warning_lead_days']}일", border=True)
        c2.metric("사건 → 대응안", f"{ks['kr_briefing_delay_days']}일", border=True)
        c3.metric("평상시 알림 비율", f"{ks['kr_calm_money_alert_rate']:.2%}", border=True)
        c4.metric("사전 알림 사건 / 기준선", f"{ks['kr_events_with_prior_warning']:.0%} / {ks['kr_base_rate']:.0%}", border=True)
        st.dataframe(pd.DataFrame([{
            "사건": r["event_id"], "첫 자금 이상 알림": r["first_kr_money_alert"], "선행일": r["kr_warning_lead_days"],
            "원인(알림)": ", ".join(f"{k_} z={v:+.2f}" for k_, v in r["kr_money_alert_cause"].items()),
            "첫 대응안": r["first_kr_alert"], "지연": r["kr_briefing_delay_days"],
            "원인(대응안)": ", ".join(f"{k_} z={v:+.2f}" for k_, v in r["kr_alert_cause"].items()),
            "글로벌 선행일": r["global_warning_lead_days"]} for r in kr["events"]]).astype(str), hide_index=True, width="stretch")
        for note in kr["notes"]:
            st.caption(note)
