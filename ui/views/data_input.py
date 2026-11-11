"""데이터 입력 — 보유내역(엑셀·CSV → 공통 스키마)과 대응 문서(PDF·워드·텍스트 → 조항)."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from app import audit, dashboard, export
from app.ingest.documents import ingest_document
from app.ingest.mapper import ColumnMap, MappingSpec
from app.ingest.pipeline import pick_sheet, propose
from app.ingest.profile import profile_text
from app.ingest.reader import read_file
from app.ingest.schema import FIELDS
from app.ingest.transform import apply_spec, save_preset, to_portfolio
from ui import common as ui

SAMPLES = ui.ROOT / "data" / "ingest" / "samples"
DOC_SAMPLES = ui.ROOT / "data" / "ingest" / "doc_samples"

ui.page_header("데이터 입력", "기관의 실제 보유내역과 대응 문서를 올리면 노출 지도와 브리핑에 반영한다. "
               "보유 종목명은 외부 LLM에 보내지 않는다.", eyebrow="데이터 · 07")


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


ui.summary_box(dashboard.data_input(st.session_state.get("uploaded_portfolio"), st.session_state.get("uploaded_holdings"),
                                    st.session_state.get("uploaded_playbooks")))
if st.session_state.get("uploaded_holdings"):
    held = pd.DataFrame(st.session_state["uploaded_holdings"])
    g1, g2 = st.columns(2)
    ui.chart(dashboard.weight_chart(held, "sector", "반영 중 포트폴리오 · 업종 비중"), g1)
    ui.chart(dashboard.weight_chart(held, "country", "반영 중 포트폴리오 · 국가 비중"), g2)

t_hold, t_doc = st.tabs(["보유내역 (엑셀·CSV)", "대응 문서 (PDF·워드·텍스트)"])

# ---------- 보유내역 ----------
with t_hold:
    st.caption("파일 모양이 달라도 된다. 라이브러리가 표 구조를 읽어 글로 요약하고, LLM은 그 요약만 보고 열 매핑 규칙을 제안한다. "
               "숫자 변환·검증은 코드가 전체 행에 적용한다. 같은 양식은 저장해 두면 다음부터 LLM 없이 변환한다. "
               "공통 스키마는 SEC N-PORT 보유 항목과 ISO 표준(ISIN 6166 · 국가 3166 · 통화 4217)에 맞춘 내부 표준이다.")
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    up = c1.file_uploader("보유내역 파일", type=["xlsx", "xlsm", "csv"])
    samples = sorted(p.name for p in SAMPLES.glob("*.*") if p.suffix in (".xlsx", ".csv"))
    sample = c2.selectbox("또는 예시 파일", ["(선택 안 함)"] + samples)
    use_llm = st.toggle("LLM 매핑 제안 사용 (헤더·샘플 요약만 전송)", value=False)
    src = name = None
    if up is not None:
        src, name = up.getvalue(), up.name
    elif sample != "(선택 안 함)":
        src, name = (SAMPLES / sample).read_bytes(), sample
    sheet = prof = None
    if src is not None:
        try:
            sheet, prof = pick_sheet(read_file(src, name))
        except (ValueError, IndexError) as e:
            st.error(f"파일을 읽지 못했다: {e}", icon=":material/error:")
    if prof is not None:
        with st.expander("① 표 구조 요약 — LLM에 보내는 글", icon=":material/summarize:"):
            st.code(profile_text(prof), language=None)
        key = f"spec_{_digest(src)}_{use_llm}"  # 같은 이름의 다른 파일이 예전 매핑을 쓰지 않게 내용 해시로
        if key not in st.session_state:
            llm = None
            if use_llm:
                from app.llm.client import LLMClient

                llm = LLMClient(db_mode="sandbox")
            with st.spinner("매핑 규칙 만드는 중…"):
                st.session_state[key] = propose(sheet, prof, llm)
        spec: MappingSpec = st.session_state[key]
        ui.section("② 열 매핑 제안", f"방식 {spec.method} · 헤더 {spec.header_row}행 · 표에서 바로 고칠 수 있다")
        edited = st.data_editor(pd.DataFrame([c.model_dump() for c in spec.columns]), num_rows="dynamic", hide_index=True,
                                width="stretch", key=f"editor_{key}", column_config={
                                    "field": st.column_config.SelectboxColumn("필드", options=list(FIELDS)),
                                    "source": st.column_config.SelectboxColumn("원본 열", options=prof.headers),
                                    "multiplier": st.column_config.NumberColumn("금액 단위 배수"),
                                    "percent": st.column_config.CheckboxColumn("% → ÷100"),
                                    "reason": st.column_config.TextColumn("근거", width="large")})
        if spec.defaults:
            st.caption("기본값: " + "; ".join(f"{k}={v} ({spec.default_reasons.get(k, '')})" for k, v in spec.defaults.items()))
        for n in spec.notes:
            st.warning(n, icon=":material/report:")
        spec = spec.model_copy(update={"columns": [ColumnMap(**{k: v for k, v in r.items() if pd.notna(v) or k == "reason"})
                                                    for r in edited.to_dict("records") if r.get("field") and r.get("source")]})
        res = apply_spec(sheet, prof, spec)
        ui.section("③ 변환 결과와 검증", "원인 → 근거 → 결과")
        ui.show_chain(res.chain)
        g1, g2 = st.columns(2)
        ui.chart(dashboard.weight_chart(res.holdings, "sector", "변환 결과 · 업종 비중"), g1)
        ui.chart(dashboard.weight_chart(res.holdings, "country", "변환 결과 · 국가 비중"), g2)
        with st.expander(f"변환된 보유 {len(res.holdings)}행 (상위 200)", icon=":material/table_rows:"):
            st.dataframe(res.holdings.head(200).round({"weight": 6}).astype(str), hide_index=True, width="stretch")
        if res.dropped:
            st.caption(f"제외 {len(res.dropped)}행: " + "; ".join(f"{d['row']}행 {d['reason']}" for d in res.dropped[:5]))
        c1, c2, c3 = st.columns(3)
        c1.download_button("공통 스키마 엑셀 받기", data=export.holdings_xlsx(res.holdings, res.chain),
                           file_name="holdings_standard.xlsx", icon=":material/download:", width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if c2.button("이 양식 저장 (다음부터 LLM 없이)", icon=":material/bookmark_add:", width="stretch"):
            st.success(f"저장: {save_preset(prof, spec, name).name}")
        if c3.button("이 포트폴리오로 분석", type="primary", disabled=res.holdings.empty, icon=":material/check:",
                     width="stretch"):
            try:
                portfolio = to_portfolio(res.holdings, institution=name)
            except ValueError as e:
                st.error(str(e), icon=":material/error:")
            else:
                st.session_state["uploaded_portfolio"] = portfolio
                st.session_state["uploaded_holdings"] = res.holdings[["name", "isin", "weight", "country", "sector", "source_row"]] \
                    .astype(object).where(res.holdings.notna(), None).to_dict("records")
                audit.log("upload_portfolio", {"file_sha256": audit.sha256_bytes(src), "rows": int(len(res.holdings)),
                                               "dropped": len(res.dropped), "mapping": spec.method, "llm": use_llm},
                          actor=ui.user_id())
                st.toast("노출 지도와 브리핑(가정 분석·라이브)에 업로드 포트폴리오를 반영했다.")
                st.rerun()  # 위쪽 흐름 띠·요약에 바로 반영
    if st.session_state.get("uploaded_portfolio") is not None and st.button("업로드 포트폴리오 해제", icon=":material/close:"):
        for k in ("uploaded_portfolio", "uploaded_holdings"):
            st.session_state.pop(k, None)
        st.rerun()

# ---------- 대응 문서 ----------
with t_doc:
    st.caption("문서를 조항으로 나누고(번호·조문 패턴, 원문 그대로), LLM은 조항마다 전제 사건·채널·조치·담당만 채운다. "
               "담당은 원문에 적힌 부서명만, 법규·보험 보호는 원문 인용 근거가 있을 때만 인정한다. LLM을 끄면 규칙만으로 분해한다.")
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    doc_files = c1.file_uploader("대응 문서", type=["pdf", "docx", "txt", "md"], accept_multiple_files=True)
    doc_samples = sorted(p.name for p in DOC_SAMPLES.glob("*.*") if p.suffix in (".pdf", ".docx"))
    doc_pick = c2.multiselect("또는 예시 문서", doc_samples)
    doc_llm = st.toggle("LLM 속성 채우기 사용 (조항 원문 전송)", value=False, key="doc_llm")
    docs = [(f.getvalue(), f.name) for f in doc_files or []] + [((DOC_SAMPLES / n).read_bytes(), n) for n in doc_pick]
    if docs:
        llm = None
        if doc_llm:
            from app.llm.client import LLMClient

            llm = LLMClient(db_mode="sandbox")
        results = []
        for data, name in docs:
            key = f"doc_{_digest(data)}_{doc_llm}"
            if key not in st.session_state:
                with st.spinner(f"{name} 변환 중…"):
                    try:
                        st.session_state[key] = ingest_document(data, name, llm=llm)
                    except ValueError as e:
                        st.error(f"{name}: {e}", icon=":material/error:")
                        continue
            results.append((data, st.session_state[key]))
        for i, (_, r) in enumerate(results):
            with st.container(border=True, key=f"doc-{i}"):
                h1, h2 = st.columns([3, 1], vertical_alignment="center")
                h1.markdown(f"**{r.playbook.title}** &nbsp; :gray[`{r.playbook.doc_id}` · 조항 {len(r.playbook.clauses)}개]")
                h2.download_button("플레이북 JSON", data=r.playbook.model_dump_json(indent=2), icon=":material/download:",
                                   file_name=f"{r.playbook.doc_id}.json", mime="application/json", key=f"dl_{i}_{r.playbook.doc_id}",
                                   width="stretch")
                ui.show_chain(r.chain)
                with st.expander("조항 표", icon=":material/table_rows:"):
                    st.dataframe(pd.DataFrame(r.rows).astype(str), hide_index=True, width="stretch")
        d1, d2 = st.columns([3, 1], vertical_alignment="bottom")
        d1.radio("분석에 쓸 문서", ["업로드 문서만", "기본 문서와 함께"], horizontal=True, key="doc_mode")
        if d2.button("이 문서로 분석", type="primary", disabled=not any(r.playbook.clauses for _, r in results),
                     icon=":material/check:", width="stretch"):
            st.session_state["uploaded_playbooks"] = [r.playbook for _, r in results if r.playbook.clauses]
            st.session_state["uploaded_doc_mode"] = st.session_state.get("doc_mode", "업로드 문서만")
            audit.log("upload_documents", {"docs": [{"file_sha256": audit.sha256_bytes(d), "doc_id": r.playbook.doc_id,
                                                     "clauses": len(r.playbook.clauses)} for d, r in results],
                                           "mode": st.session_state["uploaded_doc_mode"], "llm": doc_llm}, actor=ui.user_id())
            st.toast("브리핑에 업로드 문서를 반영했다. 브리핑에서 '업로드 데이터로 분석'을 누른다.")
            st.rerun()
    if st.session_state.get("uploaded_playbooks") and st.button("업로드 문서 해제", icon=":material/close:"):
        st.session_state.pop("uploaded_playbooks", None)
        st.rerun()
