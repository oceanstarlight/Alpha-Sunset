"""Alpha Sunset — Streamlit UI (5탭: 감시 / 브리핑 / 승인 / 백테스트 / 학습 층)."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Streamlit Cloud: 저장소 루트를 import 경로에

import pandas as pd
import streamlit as st

from app import services
from app.agents import sentinel
from app.corpus import load_events, load_playbooks
from app.schemas import AlertLevel, Briefing, Feedback, Verdict

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


def synthetic_badge():
    st.badge("합성 데이터: 대응문서·포트폴리오·라벨은 가상으로 재구성", icon="⚠️", color="orange")


# ---------- 사이드바 ----------

st.sidebar.title("🌅 Alpha Sunset")
st.sidebar.caption("위기 사건 ↔ 대응문서 적합도 판단 + 보유 자산 노출 경고")
mode = st.sidebar.radio("모드", ["백테스트 재생", "라이브"], horizontal=True)
event_ids = list(events_by_id())
event_id = st.sidebar.selectbox(
    "사건", event_ids, format_func=lambda i: f"{events_by_id()[i].date} · {events_by_id()[i].title}",
    disabled=mode == "라이브",
)
user_id = st.sidebar.text_input("검토자", value="reviewer")
st.sidebar.divider()
st.sidebar.caption("에이전트는 제안만 하고 최종 결정은 사람이 승인한다. 문서를 삭제·폐기하지 않는다.")


def current_briefing() -> Briefing | None:
    key = "live_briefing" if mode == "라이브" else f"briefing_{event_id}"
    if key not in st.session_state and mode != "라이브":
        st.session_state[key] = services.load_saved_briefing(event_id)
    return st.session_state.get(key)


tab_watch, tab_brief, tab_approve, tab_bt, tab_learn = st.tabs(["감시", "브리핑", "승인", "백테스트", "학습 층"])

# ---------- 1. 감시 ----------

with tab_watch:
    if mode == "백테스트 재생":
        e = events_by_id()[event_id]
        st.subheader(f"{e.title} 전후 경보 재생")
        st.caption("1단계 자금 이상 알림 = 시장 신호(A) 또는 자금 흐름(C). 2단계 대응안 = 사건 확정(B) + 1단계 → ALERT. 기준일까지 공개된 정보만 사용.")
        df = replay_signals(event_id)
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
        st.dataframe(df, hide_index=True, width="stretch")
    else:
        st.subheader("라이브 감시")
        st.caption("FRED 최신값과 GDELT 기사량을 조회한다. GDELT는 5초당 1회 제한이라 1분 가량 걸린다 (1시간 캐시).")
        if st.button("신호 조회", type="primary"):
            with st.spinner("FRED·GDELT 조회 중…"):
                st.session_state["signals"] = services.get_signals()
        sig = st.session_state.get("signals")
        if sig:
            level = AlertLevel(sig["level"])
            st.markdown(f"### 등급: :{LEVEL_COLOR[level]}[{level.value}]  (기준일 {sig['as_of']})")
            if sig.get("money_alert"):
                st.warning("1단계 자금 이상 알림: 시장 또는 자금 흐름에서 이상이 감지됐다. 사건이 확정되면 대응안을 생성한다.")
            if sig.get("flow"):
                st.caption("자금 흐름(C): " + ", ".join(f"{k} {v:+.2f}" for k, v in sig["flow"]["zscores"].items()))
            c1, c2 = st.columns(2)
            c1.write("**시그널 A (시장)**")
            c1.dataframe(pd.DataFrame(sig["market"]["zscores"].items(), columns=["시리즈", "z-score"]), hide_index=True)
            c2.write("**시그널 B (뉴스)**")
            if sig["news"]["clusters"]:
                c2.dataframe(pd.DataFrame(sig["news"]["clusters"]), hide_index=True)
            else:
                c2.info("기사량 급증 군집 없음")
            if sig["news"]["errors"]:
                c2.warning(f"GDELT 조회 실패 {len(sig['news']['errors'])}건 (요청 제한 등)")
            if sig["fred_error"]:
                st.warning(f"FRED 갱신 실패, 커밋된 캐시 사용: {sig['fred_error']}")
            if sig["news"]["clusters"] and st.button("탐지 사건 브리핑 생성"):
                with st.spinner("에이전트 실행 중…"):
                    st.session_state["live_briefing"] = services.run_live(sig)

# ---------- 2. 브리핑 ----------


def exposure_dot(b: Briefing) -> str:
    lines = ['digraph G { rankdir=LR; node [shape=box, style=rounded, fontsize=10];']
    edges = set()
    for p in b.exposure_entities + b.exposure_core + b.exposure_top:
        for a, c in zip(p.nodes, p.nodes[1:]):
            edges.add((a, c))
    lines += [f'"{a}" -> "{c}";' for a, c in sorted(edges)]
    return "\n".join(lines + ["}"])


with tab_brief:
    b = current_briefing()
    if mode == "백테스트 재생":
        c1, c2 = st.columns([3, 1])
        c1.caption("커밋된 재생 결과를 표시한다. 다시 실행하면 캐시된 LLM 응답으로 같은 결과를 재현한다.")
        if c2.button("재생 다시 실행"):
            with st.spinner("에이전트 실행 중…"):
                st.session_state[f"briefing_{event_id}"] = b = services.run_replay(event_id)
    if b is None:
        st.info("브리핑이 없다. 라이브 모드는 감시 탭에서 신호 조회 후 생성한다.")
    else:
        synthetic_badge()
        st.markdown(f"## {b.event.title}  :{LEVEL_COLOR[b.alert_level]}[{b.alert_level.value}]")
        st.write(b.event.summary)
        st.caption(f"유형 {b.event.type.value} · 채널 {', '.join(c.value for c in b.event.channels)} · "
                   f"지역 {', '.join(b.event.regions)} · 심각도 {b.event.severity} · run {b.run_id}")

        st.markdown("### 문서별 적합도")
        if b.match.low_confidence:
            st.warning("판정 평균 신뢰도가 낮다 (low_confidence)")
        clauses = clauses_by_id()
        docs = docs_by_id()
        table = pd.DataFrame([{"순위": i, "문서": f.doc_id, "제목": docs[f.doc_id].title if f.doc_id in docs else "",
                               "fit_score": f.fit_score, "적용": f.n_applicable, "부분": f.n_partial,
                               "부적용": f.n_not, "불확실": f.n_uncertain}
                              for i, f in enumerate(b.match.doc_fits, start=1)])
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
            st.error("사건 기관과 같은 발행자를 보유: " + ", ".join(p.nodes[3] for p in b.exposure_entities))
        if b.exposure_core:
            st.warning("핵심 경로 (사건 지역과 직접 겹치지만 비중이 작아 상위 10 밖): "
                       + " / ".join(" → ".join(p.nodes[1:]) for p in b.exposure_core))
        if b.exposure_top:
            st.dataframe(pd.DataFrame([{"경로": " → ".join(p.nodes[1:]), "risk_score": p.risk_score, "비중": p.weight,
                                        "연관도": p.relevance, "불확실성": p.uncertainty, "이유": p.why}
                                       for p in b.exposure_top]), hide_index=True, width="stretch")
            st.graphviz_chart(exposure_dot(b))

        st.markdown("### 확인 항목 (담당별)")
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
        st.info("브리핑이 없다.")
    else:
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
            st.success("승인 기록")
        if c2.button("반려"):
            services.record_approval(b, "rejected", user_id, note)
            st.warning("반려 기록")

# ---------- 4. 백테스트 ----------

with tab_bt:
    res = services.get_backtest_results()
    st.subheader("백테스트 결과")
    st.caption("실제 실행값만 표시한다. 정답 라벨 기반 지표(top3 적중, P/R)는 라벨 작성 후 P8에서 산출한다.")
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
    if lr:
        st.markdown("**ON/OFF 비교 (시뮬레이션 기반, 사전 등록 v4)**")
        c1, c2 = st.columns(2)
        c1.metric("실제 순서 1회 재생 delta", lr["pass_A"]["learner_delta"],
                  help=f"OFF {lr['pass_A']['doc_top3_hit_off']} / ON {lr['pass_A']['doc_top3_hit_on']}")
        c2.metric("반복 2회차 delta", lr["pass_B"]["learner_delta_sim"],
                  help=f"OFF {lr['pass_B']['doc_top3_hit_off']} / ON {lr['pass_B']['doc_top3_hit_on']}")
        st.dataframe(pd.DataFrame(lr["pass_B"]["events"])[["event_id", "as_of", "top3_off", "top3_on", "hit_off", "hit_on", "priority_top"]],
                     hide_index=True, width="stretch")
        for c in lr["caveats"]:
            st.caption("⚠️ " + c)
    pr = services.get_priority()
    st.markdown("**인용·피드백 기록 (shadow_log, 백테스트·승인 탭 피드백)**")
    if pr["docs"]:
        st.dataframe(pd.DataFrame(pr["docs"]), hide_index=True, width="stretch")
    else:
        st.info("아직 기록된 인용·피드백이 없다.")
