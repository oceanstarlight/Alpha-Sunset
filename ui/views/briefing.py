"""브리핑 — 사건 ↔ 대응 문서 적합도, 공백 채널, 보유 노출, 담당별 확인 항목."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd
import streamlit as st

from app import dashboard, export, services
from app.schemas import AlertLevel, Briefing
from ui import common as ui

SCENARIO_NOTE = "가정 시나리오 — 사건은 사용자 입력이고 자동 감시 근거가 아니다"

ui.page_header("브리핑", "사건에 맞는 대응 문서와 조항, 대응 공백, 보유 자산 노출, 담당별 확인 항목을 한 화면에 모은다.",
               eyebrow="운영 · 02")


# ---------- 실행 패널 ----------


def ondemand_panel() -> None:
    """감시 등급과 상관없이 지금 브리핑을 직접 실행 (현재 감시 신호 기준)."""
    sig = services.load_local_signals() if ui.is_local() else (st.session_state.get("signals") or services.get_signals())
    with st.container(border=True, key="run-ondemand"):
        if not sig:
            st.markdown("**지금 브리핑 실행**")
            st.caption("감시 신호가 아직 없다. 감시 페이지에서 조회한 뒤 실행한다.")
            return
        level = AlertLevel(sig.get("level", "NONE"))
        topics, default, why = services.ondemand_topics(sig)
        st.markdown(f"**지금 브리핑 실행** &nbsp; {ui.level_badge(level)} "
                    f"{'대한민국' if ui.is_local() else '글로벌'} 감시 등급 · 사건 확인 여부와 상관없이 실행")
        if not topics:
            st.caption("뉴스 관측이 없어 주제를 고를 수 없다. 아래 시나리오 브리핑을 쓴다.")
            return
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        topic = c1.selectbox("주제", topics, index=topics.index(default) if default in topics else 0,
                             format_func=lambda v: f"{ui.TYPE_KO.get(v, v)} ({v})", key=f"od_topic_{ui.market_view()}")
        if c2.button("지금 브리핑 실행", type="primary", key="od_run", icon=":material/play_arrow:", width="stretch"):
            event = services.ondemand_event(sig, topic, local=ui.is_local())
            with st.spinner("에이전트 실행 중 (직접 실행)…"):
                st.session_state["live_briefing"] = services.run_ondemand(
                    event, confirmed=services.topic_confirmed(sig, topic), **ui.uploaded_args())
            st.rerun()
        st.caption(f"기본 선택: {why}")


def scenario_form(expanded: bool) -> None:
    """감시 등급과 무관하게 가정 사건으로 브리핑·노출·승인 단계를 쓴다 (자동 경보 원칙과 분리)."""
    from app.agents.matcher import RULE_CHANNELS
    from app.schemas import Channel, EventType

    with st.expander("시나리오 브리핑 — 가정 사건 입력", expanded=expanded, icon=":material/science:"):
        st.caption("자동 감시가 사건을 확인하지 않아도, 가정 사건을 직접 넣어 대응 문서 적합도·보유 노출·확인 항목을 본다. "
                   "결과에는 '가정 시나리오'로 표시되고 라이브 학습 기록(shadow_log)과 섞이지 않는다.")
        c1, c2 = st.columns(2)
        etype = c1.selectbox("사건 유형", [t.value for t in EventType], format_func=lambda v: f"{ui.TYPE_KO.get(v, v)} ({v})",
                             key="sc_type")
        sev = c2.slider("심각도", 1, 5, 3, key="sc_sev", help="1 경미 ~ 5 시스템 위기")
        title = st.text_input("제목", placeholder="예: 국내 중형 증권사 PF 부실로 단기자금시장 경색", key="sc_title")
        desc = st.text_area("상황 설명", placeholder="무엇이 일어났고 어디로 번지는지 한두 줄", key="sc_desc", height=80)
        c3, c4 = st.columns(2)
        channels = c3.multiselect("전파 채널", [c.value for c in Channel], key=f"sc_ch_{etype}",
                                  default=[c.value for c in RULE_CHANNELS[EventType(etype)]])
        regions = c4.multiselect("지역", ["KR", "US", "CN", "JP", "EU", "RU", "UA", "EM", "GLOBAL"],
                                 default=["KR"] if ui.is_local() else ["GLOBAL"], key="sc_regions")
        c5, c6 = st.columns(2)
        duration = c5.selectbox("지속기간", list(ui.DURATION_KO), index=1, format_func=ui.DURATION_KO.get, key="sc_dur")
        entities = c6.text_input("관련 기관 (쉼표 구분, 선택)", placeholder="예: 태영건설, 한국투자증권", key="sc_ent",
                                 help="보유 종목 발행자와 규칙으로만 대조한다 (외부 LLM에 보유 종목명을 보내지 않음).")
        up = ui.uploaded_args()
        if up:
            st.caption("업로드 데이터 반영: " + ", ".join({"portfolio": "포트폴리오", "playbooks": "대응 문서"}[k]
                                                    for k in ("portfolio", "playbooks") if k in up))
        if st.button("시나리오 브리핑 생성", type="primary", disabled=not (title.strip() or desc.strip()),
                     icon=":material/science:"):
            event = services.scenario_event(etype, desc, title=title, channels=channels, regions=regions, severity=sev,
                                            duration=duration, entities=[x.strip() for x in entities.split(",") if x.strip()])
            with st.spinner("에이전트 실행 중 (가정 시나리오)…"):
                st.session_state["live_briefing"] = services.run_scenario(event, **up)
            st.rerun()


def replay_controls() -> None:
    eid = ui.event_id()
    with st.container(border=True, key="run-replay"):
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        c1.markdown("**백테스트 재생 결과**")
        c1.caption("커밋된 재생 결과를 표시한다. 다시 실행하면 캐시된 LLM 응답으로 같은 결과를 재현한다.")
        if c2.button("재생 다시 실행", icon=":material/replay:", width="stretch"):
            with st.spinner("에이전트 실행 중…"):
                st.session_state[f"briefing_{eid}"] = services.run_replay(eid)
            st.rerun()
        up = ui.uploaded_args()
        if not up:
            return
        label = " + ".join(x for x in (f"포트폴리오 {up['portfolio'].institution}" if "portfolio" in up else "",
                                       f"문서 {len(st.session_state['uploaded_playbooks'])}개" if "playbooks" in up else "") if x)
        u1, u2 = st.columns([3, 1], vertical_alignment="bottom")
        if st.session_state.pop("_choose_upload", False):
            st.session_state["portfolio_choice"] = "업로드"
        # 위젯 값은 다른 페이지로 가면 지워지므로, 고른 값을 따로 둔다 (current_briefing이 읽는 키)
        st.session_state.setdefault("portfolio_choice", "기본(합성)")
        st.session_state["_portfolio_choice_w"] = st.session_state["portfolio_choice"]
        u1.radio("포트폴리오", ["기본(합성)", "업로드"], horizontal=True, key="_portfolio_choice_w",
                 on_change=lambda: st.session_state.update(portfolio_choice=st.session_state["_portfolio_choice_w"]),
                 help="업로드는 현재 보유·문서를 과거 사건에 적용한 가정 분석이다 (사건 당시와 다름).")
        if u2.button(f"업로드 데이터로 분석 ({label})", icon=":material/upload:", width="stretch"):
            with st.spinner("에이전트 실행 중 (업로드 데이터)…"):
                st.session_state[f"briefing_{eid}_upload"] = services.run_replay(eid, **up)
                st.session_state["_choose_upload"] = True
            st.rerun()


# ---------- 본문 ----------


def exposure_dot(b: Briefing) -> str:
    lines = ['digraph G { rankdir=LR; bgcolor="transparent"; '
             'node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#c9c6bd", fontname="Helvetica", fontsize=10]; '
             'edge [color="#9a978e", arrowsize=0.6];']
    edges = set()
    for p in b.exposure_entities + b.exposure_core + b.exposure_top:
        for a, c in zip(p.nodes, p.nodes[1:]):
            edges.add((a, c))
    esc = lambda s: str(s).replace('"', '\\"')  # noqa: E731
    lines += [f'"{esc(a)}" -> "{esc(c)}";' for a, c in sorted(edges)]
    return "\n".join(lines + ["}"])


def render(b: Briefing) -> None:
    kind = services.briefing_kind(b)
    ui.summary_box(dashboard.briefing(b, kind=kind))
    if kind == "scenario":
        st.warning(SCENARIO_NOTE + ". 문서 적합도·노출·확인 항목은 이 가정 사건 기준이다.", icon=":material/science:")
    elif kind == "ondemand":
        st.info("직접 실행 브리핑 — 자동 감시가 사건을 확인하지 않은 상태일 수 있다. "
                "사건은 현재 감시 신호(뉴스 관측·시장 z)로 만들었다.", icon=":material/play_arrow:")

    # 사건 머리말
    with st.container(border=True, key="event-card"):
        h1, h2 = st.columns([4, 1], vertical_alignment="top")
        h1.markdown(f"{ui.level_badge(b.alert_level)} &nbsp; :gray[{b.event.date} · {ui.TYPE_KO.get(b.event.type.value, b.event.type.value)}"
                    f" · 심각도 {b.event.severity}/5]")
        h1.markdown(f"### {b.event.title}")
        h1.write(b.event.summary)
        h1.caption(f"채널 {', '.join(c.value for c in b.event.channels)} · 지역 {', '.join(b.event.regions)} · run `{b.run_id}`")
        h2.download_button("엑셀로 내보내기", data=export.briefing_xlsx(
            b, clause_text={k: c.text for k, c in ui.all_clauses().items()}), file_name=f"alpha_sunset_{b.event.id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:",
            width="stretch")

    # 핵심 수치
    top = b.match.doc_fits[0] if b.match.doc_fits else None
    roles = {a.partition("] ")[0].lstrip("[") for a in b.actions_to_check if "] " in a}
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("1위 문서 적합도", f"{top.fit_score:.2f}" if top else "—", border=True,
              delta=top.doc_id if top else None, delta_color="off", delta_arrow="off")
    k2.metric("대응 공백 채널", f"{len(b.match.gaps)}개", border=True,
              delta=", ".join(g.value for g in b.match.gaps) or "없음", delta_color="off", delta_arrow="off")
    k3.metric("최대 노출 risk", f"{b.exposure_top[0].risk_score:.3f}" if b.exposure_top else "—", border=True,
              delta=f"비중 {b.exposure_top[0].weight:.1%}" if b.exposure_top else ("분석 불가" if b.exposure_note else None),
              delta_color="off", delta_arrow="off")
    k4.metric("확인 항목", f"{len(b.actions_to_check)}개", border=True, delta=f"담당 {len(roles)}곳", delta_color="off", delta_arrow="off")
    ui.synthetic_note()

    t_docs, t_exp, t_act, t_src = st.tabs(["문서 적합도", "보유 노출", "확인 항목", "출처 · 추적"])
    clauses, docs = ui.all_clauses(), ui.all_docs()

    with t_docs:
        if b.match.low_confidence:
            st.warning("판정 평균 신뢰도가 낮다 (low_confidence) — 사람 확인 필요", icon=":material/report:")
        gaps = ", ".join(g.value for g in b.match.gaps)
        st.markdown("**대응 공백 채널** &nbsp; " + (f":red-badge[{gaps}]" if gaps else
                    ":green-badge[없음] :gray[사건 채널을 다루는 적용·부분적용 조항이 모두 있음]"))
        ui.chart(dashboard.fit_chart(b.match.doc_fits))
        for i, f in enumerate(b.match.doc_fits[:5], start=1):
            title = docs[f.doc_id].title if f.doc_id in docs else ""
            with st.expander(f"{i}. {f.doc_id} · {title} — 적합도 {f.fit_score:.2f}", expanded=i == 1):
                for j in f.judgments:
                    c = clauses.get(j.clause_id)
                    st.markdown(f"{ui.VERDICT_BADGE[j.verdict]} **{j.clause_id}**"
                                + (" :gray-badge[:material/lock: 보호]" if c and c.protected else "")
                                + f" &nbsp; :gray[신뢰도 {j.confidence:.2f}]")
                    if c:
                        st.caption(c.text)
                    if j.evidence_quote:
                        st.markdown(f"> {j.evidence_quote}")
                    for r in j.mismatch_reasons:
                        st.markdown(f"- 불일치: {r}")
        with st.expander("문서별 적합도 표", icon=":material/table_rows:"):
            st.dataframe(pd.DataFrame([{"순위": i, "문서": f.doc_id, "제목": docs[f.doc_id].title if f.doc_id in docs else "",
                                        "fit_score": f.fit_score, "적용": f.n_applicable, "부분": f.n_partial,
                                        "부적용": f.n_not, "불확실": f.n_uncertain}
                                       for i, f in enumerate(b.match.doc_fits, start=1)]),
                         hide_index=True, width="stretch",
                         column_config={"fit_score": st.column_config.ProgressColumn("적합도", min_value=0, max_value=1,
                                                                                     format="%.2f")})

    with t_exp:
        if b.exposure_note:
            st.info(b.exposure_note, icon=":material/info:")
        if b.exposure_entities:
            st.error("사건 기관과 같은 발행자를 보유: " + ", ".join(p.nodes[-2] for p in b.exposure_entities),
                     icon=":material/priority_high:")
        if b.exposure_core:
            st.warning("핵심 경로 — 사건 지역과 직접 겹치지만 비중이 작아 상위 10 밖: "
                       + " / ".join(" → ".join(p.nodes[1:]) for p in b.exposure_core), icon=":material/route:")
        if b.exposure_top:
            ui.chart(dashboard.exposure_chart(b.exposure_top))
            st.dataframe(pd.DataFrame([{"경로": " → ".join(p.nodes[1:]), "risk_score": p.risk_score, "비중": p.weight,
                                        "연관도": p.relevance, "불확실성": p.uncertainty, "이유": p.why}
                                       for p in b.exposure_top]), hide_index=True, width="stretch",
                         column_config={"risk_score": st.column_config.NumberColumn(format="%.4f"),
                                        "비중": st.column_config.NumberColumn(format="percent"),
                                        "이유": st.column_config.TextColumn(width="large")})
            with st.expander("노출 경로 그래프", icon=":material/account_tree:"):
                st.graphviz_chart(exposure_dot(b))
        elif not b.exposure_note:
            st.caption("노출 경로 없음")

    with t_act:
        grouped = defaultdict(list)
        for a in b.actions_to_check:
            role, _, rest = a.partition("] ")
            grouped[role.lstrip("[") if rest else "기타"].append(rest or a)
        if not grouped:
            st.caption("확인 항목 없음")
        else:
            ui.chart(dashboard.actions_chart(b.actions_to_check))
            cols = st.columns(min(3, len(grouped)))
            for i, (role, items) in enumerate(sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))):
                with cols[i % len(cols)].container(border=True, key=f"role-{i}"):
                    st.html(f'<div class="as-role">{ui.esc(role)}<span>{len(items)}건</span></div>')
                    st.markdown("\n".join(f"- {it}" for it in items))

    with t_src:
        st.markdown("**출처**")
        st.markdown("\n".join(f"- {s}" for s in b.event.sources) or "출처 없음")
        st.markdown("**도구 호출 trace**")
        trace = services.get_trace(b.trace_id)
        st.dataframe(pd.DataFrame(trace) if trace else pd.DataFrame(), hide_index=True, width="stretch")


if ui.is_live():
    ondemand_panel()
    scenario_form(expanded=False)
else:
    replay_controls()

b = ui.current_briefing()
if b is None:
    ui.empty_state("브리핑 없음", "위 '지금 브리핑 실행'을 누르거나, 가정 사건은 '시나리오 브리핑'에 넣는다.",
                   icon=":material/description:")
else:
    render(b)
