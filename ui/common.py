"""페이지 공통: 사이드바 상태 접근, 캐시된 데이터, 화면 컴포넌트(머리말·요약 카드·흐름 띠·배지).

페이지 스크립트(ui/views/*.py)는 매 실행마다 새로 실행되고, 이 모듈은 한 번만 불러온다.
사이드바 위젯 값은 진입 스크립트(ui/streamlit_app.py)가 키로 session_state에 둔다.
"""

from __future__ import annotations

import html
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from app import audit, dashboard, services
from app.agents import sentinel
from app.config import load_config
from app.corpus import load_events, load_playbooks
from app.schemas import AlertLevel, Briefing, Verdict

ROOT = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent

MODE_REPLAY, MODE_LIVE = "백테스트 재생", "라이브"

# 페이지 경로 (st.navigation·st.page_link 공용, 진입 스크립트 기준 상대 경로)
PAGE_MONITOR = "views/monitor.py"
PAGE_BRIEFING = "views/briefing.py"
PAGE_APPROVAL = "views/approval.py"
PAGE_MAP = "views/exposure_map.py"
PAGE_BACKTEST = "views/backtest.py"
PAGE_LEARNER = "views/learner.py"
PAGE_INPUT = "views/data_input.py"

VERDICT_BADGE = {
    Verdict.applicable: ":green-badge[적용]",
    Verdict.partial: ":orange-badge[부분적용]",
    Verdict.not_applicable: ":gray-badge[부적용]",
    Verdict.uncertain: ":violet-badge[불확실]",
}
LEVEL_BADGE_COLOR = {AlertLevel.ALERT: "red", AlertLevel.WATCH: "orange", AlertLevel.NONE: "green"}
TYPE_KO = {"banking_stress": "은행 위기", "liquidity_crisis": "유동성 위기", "credit_event": "신용 사건(부도)",
           "rate_shock": "금리 충격", "fx_shock": "환율 충격", "trade_policy": "무역·관세", "geopolitical": "지정학",
           "pandemic": "감염병", "supply_chain": "공급망", "regulatory": "규제", "other": "기타"}
DURATION_KO = {"shock": "단기 충격", "weeks": "수 주", "months": "수 개월", "structural": "구조적"}


# ---------- 사이드바 상태 ----------


def cfg() -> dict:
    return load_config()


def local_market() -> dict:
    return cfg()["markets"]["local"]


def mode() -> str:
    return st.session_state.get("mode", MODE_REPLAY)


def is_live() -> bool:
    return mode() == MODE_LIVE


def market_view() -> str:
    return st.session_state.get("market_view", cfg()["markets"]["default_view"])


def is_local() -> bool:
    return market_view() == "local"


def event_id() -> str:
    ids = list(events_by_id())
    eid = st.session_state.get("event_id")
    return eid if eid in ids else ids[0]


def user_id() -> str:
    return (st.session_state.get("user_id") or "").strip() or "reviewer"


# ---------- 데이터 (캐시) ----------


@st.cache_resource
def events_by_id() -> dict:
    return {e.id: e for e in sorted(load_events(), key=lambda e: e.date)}


@st.cache_resource
def clauses_by_id() -> dict:
    return {c.clause_id: c for p in load_playbooks() for c in p.clauses}


@st.cache_resource
def docs_by_id() -> dict:
    return {p.doc_id: p for p in load_playbooks()}


@st.cache_resource
def market_panel():
    return services.market_panel()


@st.cache_data(ttl=600, show_spinner=False)
def backtest_results() -> dict:
    """커밋된 백테스트 결과 파일 (페이지 이동마다 다시 읽지 않게 10분 캐시)."""
    return services.get_backtest_results()


@st.cache_resource(show_spinner=False)
def replay_results(eid: str) -> list:
    """사건 전후(−30일~+14일) Sentinel 재생 — 신호 표·판단 근거·흐름 띠가 같은 결과를 함께 쓴다 (재생 1회)."""
    e = events_by_id()[eid]
    return sentinel.replay(market_panel(), [e], e.date - timedelta(days=30), e.date + timedelta(days=14))


@st.cache_data(show_spinner=False)
def replay_signals(eid: str) -> pd.DataFrame:
    return pd.DataFrame([{"날짜": r.as_of, "등급": r.level.value,
                          "자금 이상 알림": r.market.active or bool(r.flow and r.flow.active),
                          "시장 신호(A)": r.market.active, "자금 흐름(C)": bool(r.flow and r.flow.active),
                          "사건 확정(B)": r.news.active,
                          "트리거": ", ".join(r.market.triggered + (r.flow.triggered if r.flow else []))}
                         for r in replay_results(eid)])


@st.cache_data(show_spinner=False)
def replay_chains(eid: str) -> dict[str, list[dict]]:
    """재생 구간의 첫 자금 이상 알림일·첫 ALERT일 판단 근거."""
    results = replay_results(eid)
    out = {}
    first_money = next((r for r in results if r.market.active or (r.flow and r.flow.active)), None)
    first_alert = next((r for r in results if r.level == AlertLevel.ALERT), None)
    for name, r in [("첫 자금 이상 알림", first_money), ("첫 ALERT", first_alert)]:
        if r:
            out[f"{name} · {r.as_of}"] = sentinel.explain(r)
    return out


# ---------- 브리핑·업로드 상태 ----------


def briefing_key() -> str:
    return "live_briefing" if is_live() else f"briefing_{event_id()}"


def current_briefing() -> Briefing | None:
    key = briefing_key()
    if not is_live() and st.session_state.get("portfolio_choice") == "업로드" and f"{key}_upload" in st.session_state:
        return st.session_state[f"{key}_upload"]  # 업로드 포트폴리오 가정 분석 결과
    if key not in st.session_state and not is_live():
        st.session_state[key] = services.load_saved_briefing(event_id())
    return st.session_state.get(key)


def uploaded_args() -> dict:
    """업로드 포트폴리오·대응 문서가 있으면 브리핑 실행에 넘길 인자."""
    args = {}
    pf = st.session_state.get("uploaded_portfolio")
    if pf is not None:
        args |= {"portfolio": pf, "holdings": st.session_state.get("uploaded_holdings")}
    pbs = st.session_state.get("uploaded_playbooks")
    if pbs:
        # 위젯 값(doc_mode)은 다른 페이지로 가면 지워지므로 '이 문서로 분석' 시점에 저장한 값을 쓴다
        mode_ = st.session_state.get("uploaded_doc_mode", "업로드 문서만")
        args["playbooks"] = pbs if mode_ == "업로드 문서만" else load_playbooks() + pbs
    return args


def all_clauses() -> dict:
    """합성 조항 + 업로드 문서 조항 (브리핑 표시용)."""
    out = dict(clauses_by_id())
    for p in st.session_state.get("uploaded_playbooks") or []:
        out |= {c.clause_id: c for c in p.clauses}
    return out


def all_docs() -> dict:
    return docs_by_id() | {p.doc_id: p for p in st.session_state.get("uploaded_playbooks") or []}


def live_signals() -> dict | None:
    """현재 시장 보기 기준 감시 결과 (로컬 = 수집기 결과, 글로벌 = 조회한 값 또는 수집 결과)."""
    if is_local():
        return services.load_local_signals()
    return st.session_state.get("signals") or services.load_collected_signals(with_panel=False)


# ---------- 화면 컴포넌트 ----------


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def dot(tone: str) -> str:
    return f'<span class="as-dot as-dot--{esc(tone)}"></span>'


def badge(text: str, tone: str = "gray") -> str:
    """Streamlit 마크다운 배지 (:color-badge[...])."""
    color = dashboard.TONE_BADGE.get(tone, tone)
    return f":{color}-badge[{text}]"


def level_badge(level: AlertLevel | str) -> str:
    lv = AlertLevel(level) if not isinstance(level, AlertLevel) else level
    return f":{LEVEL_BADGE_COLOR[lv]}-badge[{lv.value}]"


def page_header(title: str, desc: str = "", eyebrow: str = "") -> None:
    """페이지 머리말: 분류 · 제목 · 한 줄 설명 + 현재 보기(모드·사건·시장)."""
    if is_live():
        scope = f"라이브 · {local_market()['name'] if is_local() else '글로벌'}"
    else:
        e = events_by_id()[event_id()]
        scope = f"백테스트 재생 · {e.date} {e.title}"
    st.html(
        f'<div class="as-head">'
        f'<div class="as-eyebrow">{esc(eyebrow)}<span class="as-scope">{esc(scope)}</span></div>'
        f'<h1 class="as-title">{esc(title)}</h1>'
        + (f'<p class="as-desc">{esc(desc)}</p>' if desc else "")
        + "</div>")


def section(title: str, note: str = "") -> None:
    st.html(f'<div class="as-section"><h3>{esc(title)}</h3>'
            + (f'<span>{esc(note)}</span>' if note else "") + "</div>")


_summary_seq = {"n": 0}


def begin_run() -> None:
    """실행마다 컨테이너 키 번호를 0부터 (키가 실행마다 같아야 화면이 다시 그려질 때 깜빡이지 않는다)."""
    _summary_seq["n"] = 0


def summary_box(s: dashboard.Summary) -> None:
    """요약 카드: 상태 점 + 제목, 아래 개조식(원인 → 근거 → 할 일). 왼쪽 선 색이 상태를 나타낸다."""
    _summary_seq["n"] += 1
    with st.container(border=True, key=f"summary-{s.tone}-{_summary_seq['n']}"):
        st.html(f'<div class="as-summary-head">{dot(s.tone)}<span>{esc(s.headline)}</span></div>')
        if s.bullets:
            st.markdown("\n".join(f"- {x}" for x in s.bullets))


def show_chain(chain: list[dict]) -> None:
    """원인 → 근거 → 결과 표."""
    st.dataframe(pd.DataFrame(chain), hide_index=True, width="stretch",
                 column_config={"근거": st.column_config.TextColumn(width="large")})


def chart(c, col=None) -> None:
    if c is not None:
        (col or st).altair_chart(c, width="stretch")


def synthetic_note() -> None:
    st.caption(":material/info: 대응 문서·포트폴리오·라벨은 공개 자료를 바탕으로 가상 재구성한 합성 데이터다.")


def empty_state(title: str, body: str, icon: str = ":material/inbox:") -> None:
    with st.container(border=True, key=f"empty-{abs(hash(title)) % 10**6}"):
        st.markdown(f"{icon} **{title}**")
        st.caption(body)


# ---------- 흐름 띠 (데이터 → 감시 → 브리핑 → 승인) ----------

_STEP_PAGE = {"데이터": PAGE_INPUT, "감시": PAGE_MONITOR, "브리핑": PAGE_BRIEFING, "승인": PAGE_APPROVAL}
_STEP_TITLE = {"데이터": "데이터 입력", "감시": "감시", "브리핑": "브리핑", "승인": "승인"}


def flow_steps() -> list[dashboard.Step]:
    b = current_briefing()
    if not is_live():
        e = events_by_id()[event_id()]
        df = replay_signals(event_id())
        fa = df[df["등급"] == "ALERT"]["날짜"].min()
        watch = dashboard.step_watch_replay(fa if pd.notna(fa) else None,
                                            int(((df["날짜"] < e.date) & df["자금 이상 알림"]).sum()), e.date)
    else:
        watch = dashboard.step_watch(live_signals(), local=is_local())
    return [dashboard.step_data(st.session_state.get("uploaded_portfolio"), st.session_state.get("uploaded_playbooks")),
            watch, dashboard.step_briefing(b, services.briefing_kind(b) if b else None),
            dashboard.step_approval(b, audit.read("app"))]


def flow_strip(current_title: str | None) -> None:
    """모든 페이지 위에 보이는 업무 흐름 띠. 지금 보고 있는 단계는 강조하고, 칸마다 해당 페이지로 가는 링크."""
    steps = flow_steps()
    cols = st.columns(len(steps), gap="small")
    for i, (col, s) in enumerate(zip(cols, steps), start=1):
        page = _STEP_PAGE[s.name]
        active = _STEP_TITLE[s.name] == current_title
        with col.container(border=True, key=f"flow-{'on' if active else 'off'}-{i}"):
            st.html(f'<div class="as-step"><div class="as-step-no">{i:02d} · {esc(s.name)}</div>'
                    f'<div class="as-step-status">{dot(s.tone)}{esc(s.status)}</div>'
                    f'<div class="as-step-detail">{esc(s.detail)}</div></div>')
            if not active:
                st.page_link(page, label="열기", icon=":material/arrow_forward:")


# ---------- 스타일 ----------


def inject_css() -> None:
    st.html(f"<style>{(UI_DIR / 'style.css').read_text(encoding='utf-8')}</style>")
