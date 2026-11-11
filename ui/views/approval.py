"""승인 — 문서 피드백(학습 층 입력)과 사람의 최종 결정, 감사 로그."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app import audit, dashboard, services
from app.schemas import Feedback
from ui import common as ui

ui.page_header("승인", "에이전트 제안을 사람이 검토한다. 문서별 피드백은 학습 층 입력으로만 쓰이고, "
               "승인·반려는 해시 체인 감사 로그에 남는다.", eyebrow="운영 · 03")

b = ui.current_briefing()
records = audit.read("app")

if b is None:
    ui.summary_box(dashboard.Summary("gray", "승인할 브리핑 없음", [
        "백테스트 재생 모드는 사건을 고르면 커밋된 브리핑이 뜬다",
        "라이브 모드는 감시의 사건 탐지 또는 브리핑의 지금 실행·시나리오로 만든다"]))
else:
    ui.summary_box(dashboard.approval(b, records))
    ui.synthetic_note()
    mine = [r for r in records if r.get("data", {}).get("run_id") == b.run_id]
    last_fb = {r["data"]["doc_id"]: r["data"]["label"] for r in mine if r["action"] == "feedback"}
    docs = ui.all_docs()

    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.section("문서 피드백", "학습 층이 켜졌을 때만 우선순위에 반영")
        for f in b.match.doc_fits[:6]:
            with st.container(border=True, key=f"fbrow-{f.doc_id}"):
                c1, c2, c3 = st.columns([4, 1.4, 1.6], vertical_alignment="center")
                state = {"useful": " :green-badge[유용 기록]", "not_fit": " :gray-badge[부적합 기록]"}.get(last_fb.get(f.doc_id), "")
                c1.markdown(f"**{f.doc_id}** &nbsp; {docs[f.doc_id].title if f.doc_id in docs else ''}{state}  \n"
                            f":gray[적합도 {f.fit_score:.2f} · 적용 {f.n_applicable} · 부분 {f.n_partial}]")
                for col, label, text, icon in [(c2, "useful", "유용", ":material/thumb_up:"),
                                               (c3, "not_fit", "부적합", ":material/thumb_down:")]:
                    if col.button(text, key=f"fb_{b.run_id}_{f.doc_id}_{label}", icon=icon, width="stretch",
                                  disabled=last_fb.get(f.doc_id) == label):
                        services.submit_feedback(Feedback(run_id=b.run_id, doc_id=f.doc_id, label=label,
                                                          user_id=ui.user_id()), b)
                        st.toast(f"{f.doc_id}: {text} 기록")
                        st.rerun()
    with right:
        ui.section("최종 결정")
        with st.container(border=True, key="decision"):
            st.markdown(f"**{b.event.title}**")
            st.caption(f"run `{b.run_id}` · 검토자 {ui.user_id()}")
            note = st.text_area("승인 메모", placeholder="결정 근거나 후속 조치를 한두 줄", height=90)
            c1, c2 = st.columns(2)
            if c1.button("브리핑 승인", type="primary", icon=":material/check:", width="stretch"):
                services.record_approval(b, "approved", ui.user_id(), note)
                st.rerun()
            if c2.button("반려", icon=":material/close:", width="stretch"):
                services.record_approval(b, "rejected", ui.user_id(), note)
                st.rerun()
            decisions = [r for r in mine if r["action"] == "approval"]
            if decisions:
                st.caption("결정 이력")
                st.dataframe(pd.DataFrame([{"시각(UTC)": r["ts"][:16].replace("T", " "), "결정": r["data"]["decision"],
                                            "검토자": r["actor"], "메모": r["data"].get("note", "")}
                                           for r in decisions[::-1]]), hide_index=True, width="stretch")

# ---------- 감사 로그 ----------

ui.section("감사 로그", "추가 전용 · 해시 체인")
st.caption("승인·피드백·브리핑 생성·업로드·학습 층 토글·자동 알림을 한 줄씩 남긴다. 줄마다 앞 줄 해시를 품고 있어 "
           "중간 줄을 고치거나 지우면 검증이 깨진다. 업로드는 파일 이름·내용 대신 해시와 건수만 남긴다. "
           "자동 감시 기록은 저장소에 커밋되고, 앱 기록(app)은 이 서버에만 남으니 내려받아 보관한다.")
srcs = audit.sources()
if not srcs:
    ui.empty_state("기록 없음", "피드백·승인·업로드를 하면 이곳에 쌓인다.", icon=":material/receipt_long:")
for s in srcs:
    v = audit.verify(s)
    rows = audit.read(s)
    with st.expander(f"{s} · {v.n}줄 · {'검증 통과' if v.ok else '검증 실패'}", icon=":material/verified:" if v.ok else ":material/error:",
                     expanded=not v.ok):
        c1, c2 = st.columns([4, 1], vertical_alignment="center")
        if v.ok:
            c1.markdown(":green-badge[체인 검증 통과]" + (f" &nbsp; :gray[마지막 해시 `{rows[-1]['hash'][:12]}…`]" if rows else ""))
        else:
            c1.markdown(f":red-badge[검증 실패] seq {v.bad_seq}: {v.reason}")
        c2.download_button("JSONL 받기", data=audit.path_for(s).read_bytes(), file_name=f"audit_{s}.jsonl",
                           mime="application/json", key=f"audit_dl_{s}", icon=":material/download:", width="stretch")
        if rows:
            st.dataframe(pd.DataFrame([{"seq": r["seq"], "ts": r["ts"], "action": r["action"], "actor": r["actor"],
                                        "data": json.dumps(r["data"], ensure_ascii=False)[:200]} for r in rows[-50:][::-1]]),
                         hide_index=True, width="stretch")
