"""노출 지도 — 사건 지역·국가별 보유 비중·사건 영향도."""

from __future__ import annotations

import pydeck as pdk
import streamlit as st

from app import dashboard, geo
from app.agents.exposure import ExposureUnavailable
from app.corpus import load_portfolio
from app.schemas import Event
from ui import common as ui

LOCAL = ui.local_market()
is_local, live = ui.is_local(), ui.is_live()

ui.page_header(f"노출 지도 · {LOCAL['name']} 중심" if is_local else "노출 지도 · 세계",
               "사건이 일어난 지역과 보유 자산이 몰린 국가, 그 둘이 겹쳐 생기는 영향도를 한 지도에 겹쳐 본다.",
               eyebrow="분석 · 04")


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


b = ui.current_briefing()
map_event = (b.event if b else None) if live else ui.events_by_id()[ui.event_id()]
snapshot = "live" if live else ui.event_id()
uploaded = st.session_state.get("uploaded_portfolio")
if uploaded is not None:  # 데이터 입력에서 올린 실제 보유내역
    try:
        exp = geo.country_exposure(uploaded, snapshot)
        imp = geo.country_impact(map_event, uploaded, snapshot) if map_event else None
    except ExposureUnavailable:
        exp = imp = None
else:
    exp = map_exposure(snapshot)
    imp = map_impact(map_event.model_dump_json(), snapshot) if map_event else None

c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
options = [v["label"] for v in geo.LAYERS.values()]
shown = c1.pills("레이어", options, selection_mode="multi", default=options) or []
c2.caption(f"포트폴리오: 업로드 ({uploaded.institution}, 노드 {len(uploaded.nodes)}개)" if uploaded is not None
           else "포트폴리오: 기본(합성)")

df, unmapped = geo.map_rows(
    event=map_event if geo.LAYERS["event"]["label"] in shown else None,
    exposure_by_country=exp if geo.LAYERS["exposure"]["label"] in shown else None,
    impact_by_country=imp if geo.LAYERS["impact"]["label"] in shown else None,
)
# 한국 중심(확대) 보기에서는 원이 화면을 덮지 않게 반경을 줄인다
radius_scale = 0.35 if is_local else 1.0


def scatter(k: str, v: dict) -> pdk.Layer:
    ring = k == "event"  # 사건은 테두리 원으로 그려 아래 원(비중·영향도)이 가려지지 않게
    return pdk.Layer("ScatterplotLayer", data=df[df["layer"] == v["label"]], get_position=["lon", "lat"],
                     get_radius="radius", radius_scale=radius_scale, get_fill_color="color", filled=not ring,
                     stroked=True, pickable=True,
                     get_line_color=v["color"][:3] + [230] if ring else [255, 255, 255, 180],
                     line_width_min_pixels=2 if ring else 1, radius_min_pixels=3)


layers = [scatter(k, v) for k, v in geo.LAYERS.items() if not df.empty and v["label"] in set(df["layer"])]
with st.container(border=True, key="map-card"):
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=(
        pdk.ViewState(latitude=LOCAL["lat"], longitude=LOCAL["lon"], zoom=3.4) if is_local
        else pdk.ViewState(latitude=25, longitude=30, zoom=0.9)), tooltip={"text": "{tooltip}"}), height=500)
    st.html('<div class="as-legend">'
            f'<span><i class="ring"></i>{ui.esc(geo.LAYERS["event"]["label"])} — 크기 = 심각도</span>'
            f'<span><i style="background:rgba(37,99,235,.55)"></i>{ui.esc(geo.LAYERS["exposure"]["label"])} — 국가별 노드 비중</span>'
            f'<span><i style="background:rgba(249,115,22,.75)"></i>{ui.esc(geo.LAYERS["impact"]["label"])} — risk_score 합</span>'
            "</div>")
    st.caption("보유 비중은 프록시 펀드 보유 국가를 반영하고 거래상대방을 포함한다. 영향도 = 비중 × 연관도 × 불확실성 감점 "
               "(LLM 없이 규칙 매칭).")

if map_event:
    st.markdown(f"**사건** {map_event.title} :gray[({map_event.date} · 지역 {', '.join(map_event.regions)} · "
                f"심각도 {map_event.severity}/5)]")
elif live:
    st.info("라이브 사건 브리핑이 없어 사건·영향도 원은 표시하지 않는다 (감시에서 사건 탐지 또는 브리핑에서 직접 실행).",
            icon=":material/info:")
if exp is None:
    st.warning(f"{snapshot} 시점 보유 스냅샷이 없어 보유 비중·영향도를 그릴 수 없다 (N-PORT 2019년 이전 미공개).",
               icon=":material/cloud_off:")
if is_local and not df.empty:
    loc = df[df["code"] == LOCAL["code"]].set_index("layer")["value"]
    m1, m2, m3 = st.columns(3)
    m1.metric(f"{LOCAL['name']} 보유 비중", f"{loc.get(geo.LAYERS['exposure']['label'], 0):.1%}", border=True)
    m2.metric(f"{LOCAL['name']} 영향도", f"{loc.get(geo.LAYERS['impact']['label'], 0):.4f}", border=True)
    m3.metric(f"{LOCAL['name']} 사건 지역", "예" if geo.LAYERS["event"]["label"] in loc.index else "아니오", border=True)
g1, g2 = st.columns(2)
ui.chart(dashboard.country_chart(exp, "국가별 보유 비중 상위"), g1)
ui.chart(dashboard.country_chart(imp, "국가별 사건 영향도 상위", fmt=".3f"), g2)
if not df.empty:
    with st.expander("레이어별 상위 5개국", icon=":material/table_rows:"):
        top = (df.sort_values("value", ascending=False).groupby("layer").head(5)
               [["layer", "name", "code", "value"]].rename(columns={"layer": "레이어", "name": "국가", "code": "코드", "value": "값"}))
        st.dataframe(top, hide_index=True, width="stretch")
if unmapped:
    st.caption("좌표로 표시하지 못한 지역(묶음·미상): " + "; ".join(f"{geo.LAYERS[k]['label']} {', '.join(v)}"
                                                       for k, v in unmapped.items()))
