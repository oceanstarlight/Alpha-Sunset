"""학습 층 (알파 썬셋) — 인용·피드백으로 문서 검색 우선순위를 조정. 기본 OFF."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app import dashboard, services
from ui import common as ui

ui.page_header("학습 층", "자주 유용했던 문서의 검색 우선순위를 올리고 거의 쓰이지 않는 문서는 내린다. 문서는 삭제·폐기하지 않고, "
               "protected 문서는 우선순위 하한 0.5로 항상 후보에 남는다.", eyebrow="분석 · 06")

summary_slot = st.empty()
current = services.learner_enabled()
with st.container(border=True, key="learner-toggle"):
    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    enabled = c1.toggle("학습 층 사용", value=current,
                        help="켜면 브리핑 문서 순위에 final = fit × (1 + 0.3·(priority − 0.5))를 적용한다. 변경 이력이 남는다.")
    c2.caption("보정 폭은 최대 ±15% — 적합도 차이를 뒤집을 만큼 크지 않게 보수적으로 설계했다.")
if enabled != current:
    services.set_learner_enabled(enabled)
    st.toast(f"학습 층 {'ON' if enabled else 'OFF'} (변경 이력 기록)")

lr = ui.backtest_results().get("learner")
pr = services.get_priority()
with summary_slot.container():
    ui.summary_box(dashboard.learner(enabled, pr["docs"], lr["pass_B"]["learner_delta_sim"] if lr else None))

left, right = st.columns([3, 2], gap="large")
with left:
    ui.chart(dashboard.priority_chart(pr["docs"]))
    ui.section("인용·피드백 기록", "shadow_log · 백테스트·승인 피드백")
    if pr["docs"]:
        st.dataframe(pd.DataFrame(pr["docs"]), hide_index=True, width="stretch")
    else:
        ui.empty_state("기록 없음", "브리핑이 만들어지거나 승인 페이지에서 피드백을 남기면 쌓인다.", icon=":material/history:")
with right:
    if lr:
        ui.section("ON/OFF 비교", "시뮬레이션 · 사전 등록 v4")
        c1, c2 = st.columns(2)
        c1.metric("1회 재생 delta", lr["pass_A"]["learner_delta"], border=True,
                  help=f"top3 적중 OFF {lr['pass_A']['doc_top3_hit_off']} / ON {lr['pass_A']['doc_top3_hit_on']}")
        c2.metric("반복 2회차 delta", lr["pass_B"]["learner_delta_sim"], border=True,
                  help=f"top3 적중 OFF {lr['pass_B']['doc_top3_hit_off']} / ON {lr['pass_B']['doc_top3_hit_on']}")
        for c in lr["caveats"]:
            st.caption(c)

if lr:
    with st.expander("반복 재생 사건별 결과", icon=":material/table_rows:"):
        sim = pd.DataFrame(lr["pass_B"]["events"])[["event_id", "as_of", "top3_off", "top3_on", "hit_off", "hit_on", "priority_top"]]
        # [문서, 점수] 쌍 목록은 Arrow 직렬화가 안 되므로 문자열로 표시
        sim["priority_top"] = sim["priority_top"].map(lambda xs: ", ".join(f"{d}({p:.2f})" for d, p in xs))
        for col in ("top3_off", "top3_on"):
            sim[col] = sim[col].map(", ".join)
        st.dataframe(sim, hide_index=True, width="stretch")
