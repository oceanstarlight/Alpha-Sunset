"""Alpha Sunset — Streamlit 진입 스크립트.

사이드바 내비게이션(운영: 감시·브리핑·승인 / 분석: 노출 지도·백테스트·학습 층 / 데이터: 데이터 입력)과
보기 설정(시장·모드·사건·검토자), 모든 페이지 위의 업무 흐름 띠를 그린 뒤 선택한 페이지(ui/views/*.py)를 실행한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # Streamlit Cloud: 저장소 루트를 import 경로에


def _code_stamp() -> str:
    """app/·ui/ 코드와 config.yaml의 수정 상태. 바뀌면 모듈을 새로 불러온다.

    Streamlit은 메인 스크립트 폴더 밖 모듈을 다시 불러오지 않아, 새 커밋을 받아도 예전 app 코드가 메모리에 남는다.
    """
    files = sorted(ROOT.joinpath("app").rglob("*.py")) + sorted(ROOT.joinpath("ui").glob("*.py")) + [ROOT / "config.yaml"]
    return str(hash(tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.exists())))


_STAMP = _code_stamp()
if "app" in sys.modules and getattr(sys.modules["app"], "_code_stamp", _STAMP) != _STAMP:  # UI가 불러온 뒤 코드가 바뀐 경우만
    for _name in [m for m in sys.modules if m in ("app", "ui") or m.startswith(("app.", "ui."))]:
        del sys.modules[_name]
    _RELOADED = True
else:
    _RELOADED = False

import streamlit as st  # noqa: E402

from app.config import get_settings, load_config  # noqa: E402
from ui import common as ui  # noqa: E402

sys.modules["app"]._code_stamp = _STAMP
if _RELOADED:
    load_config.cache_clear()
    st.cache_data.clear()
    st.cache_resource.clear()

st.set_page_config(page_title="Alpha Sunset", page_icon=str(ui.UI_DIR / "assets" / "mark.svg"), layout="wide",
                   initial_sidebar_state="auto")
ui.inject_css()
ui.begin_run()
st.logo(str(ui.UI_DIR / "assets" / "logo.svg"), size="large", icon_image=str(ui.UI_DIR / "assets" / "mark.svg"))

# ---------- 내비게이션 ----------

pages = {
    "운영": [
        st.Page(ui.PAGE_MONITOR, title="감시", icon=":material/monitor_heart:", default=True),
        st.Page(ui.PAGE_BRIEFING, title="브리핑", icon=":material/description:"),
        st.Page(ui.PAGE_APPROVAL, title="승인", icon=":material/fact_check:"),
    ],
    "분석": [
        st.Page(ui.PAGE_MAP, title="노출 지도", icon=":material/public:"),
        st.Page(ui.PAGE_BACKTEST, title="백테스트", icon=":material/query_stats:"),
        st.Page(ui.PAGE_LEARNER, title="학습 층", icon=":material/tune:"),
    ],
    "데이터": [
        st.Page(ui.PAGE_INPUT, title="데이터 입력", icon=":material/upload_file:"),
    ],
}
nav = st.navigation(pages, position="sidebar")

# ---------- 보기 설정 (모든 페이지 공용, 위젯 키로 session_state에 둔다) ----------

LOCAL = ui.local_market()
with st.sidebar:
    st.html('<div class="as-side-label">보기 설정</div>')
    st.radio("시장", ["local", "global"], horizontal=True, key="market_view",
             index=0 if load_config()["markets"]["default_view"] == "local" else 1,
             help="데이터는 로컬·글로벌 모두 수집하고, 화면에 보여줄 범위만 고른다.",
             format_func=lambda v: f"로컬 ({LOCAL['name']})" if v == "local" else "글로벌")
    st.radio("모드", [ui.MODE_REPLAY, ui.MODE_LIVE], horizontal=True, key="mode",
             help="백테스트 재생은 과거 사건을 사건일 시점 정보로 다시 돌린 결과, 라이브는 지금 수집한 신호.")
    events = ui.events_by_id()
    st.selectbox("사건", list(events), key="event_id", disabled=ui.is_live(),
                 format_func=lambda i: f"{events[i].date} · {events[i].title}",
                 help="백테스트 재생 모드에서 볼 과거 사건.")
    st.text_input("검토자", value="reviewer", key="user_id", help="피드백·승인·감사 로그에 남는 이름.")
    _st = get_settings()
    engine = {"gemini": "Gemini", "openai_compatible": "OpenAI 호환",
              "rule": "규칙 판정 (LLM 없음 · 신뢰도 0.3)"}.get(_st.llm_provider, _st.llm_provider)
    if _st.llm_provider == "openai_compatible" and _st.llm_model:
        engine += f" · {_st.llm_model}"
    st.divider()
    st.html('<div class="as-side-foot">에이전트는 제안만 하고, 최종 결정은 사람이 승인한다. 문서는 삭제·폐기하지 않는다.<br>'
            f'판정 엔진 <b>{ui.esc(engine)}</b><br>'
            f'코드 버전 <b>{abs(int(_STAMP)) % 10**8:08d}</b>' + (" · 새 코드 반영됨" if _RELOADED else "") + "</div>")

# ---------- 업무 흐름 띠 + 페이지 ----------

ui.flow_strip(nav.title)
nav.run()
