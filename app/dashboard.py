"""탭 상단 요약(개조식)과 그래프 — 화면에서 바로 읽히는 현재 상황.

요약은 원인 → 근거 → 결과가 보이게 3~6줄로 만든다. 순수 함수라 테스트할 수 있고, Streamlit은 렌더만 한다.
그래프는 Altair (Streamlit 기본 포함). 색은 dataviz 기본 팔레트: 상태색(정상·주의·경고·위험)은 의미에만 쓰고
항상 아이콘·글자와 함께, 크기 비교는 파랑 한 색, 비교 기준(우연·평소)은 주황.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import altair as alt
import pandas as pd

from app.config import load_config

# dataviz 기본 팔레트 (references/palette.md)
GOOD, WARNING, SERIOUS, CRITICAL = "#0ca30c", "#fab219", "#ec835a", "#d03b3b"
BLUE, BLUE_LIGHT, ORANGE = "#2a78d6", "#86b6ef", "#eb6834"
MUTED, NEUTRAL = "#898781", "#c3c2b7"
# Streamlit은 지정 높이에 제목·축·범례까지 포함해 맞춘다 → 막대 영역 + 여유분으로 잡는다
CHROME = 120


def _h(rows: int, per: int = 34, minimum: int = 3) -> int:
    return per * max(rows, minimum) + CHROME

TONE_ICON = {"red": "🔴", "orange": "🟠", "green": "🟢", "gray": "⚪", "blue": "🔵"}
LEVEL_TONE = {"ALERT": "red", "WATCH": "orange", "NONE": "green"}
LEVEL_KO = {"ALERT": "ALERT · 대응안", "WATCH": "WATCH · 자금 이상 감시", "NONE": "NONE · 이상 없음"}
VERDICT_KO = {"applicable": "적용", "partial": "부분", "not_applicable": "부적용", "uncertain": "불확실"}
VERDICT_COLOR = {"적용": GOOD, "부분": WARNING, "부적용": NEUTRAL, "불확실": MUTED}


@dataclass
class Summary:
    tone: str
    headline: str
    bullets: list[str] = field(default_factory=list)

    @property
    def icon(self) -> str:
        return TONE_ICON.get(self.tone, "⚪")


# ---------- 요약 ----------


def _max_abs(z: dict[str, float | None]) -> tuple[str, float] | None:
    vals = [(k, v) for k, v in (z or {}).items() if v is not None]
    return max(vals, key=lambda kv: abs(kv[1])) if vals else None


def _signal_line(name: str, z: dict, triggered: list, th: float) -> str:
    if triggered:
        return f"**{name}**: 🔴 임계 초과 {', '.join(triggered)} (기준 |z| ≥ {th})"
    top = _max_abs(z)
    if top is None:
        return f"**{name}**: ⚪ 데이터 없음"
    near = abs(top[1]) >= 0.75 * th
    return f"**{name}**: {'🟠 임계 근접' if near else '🟢 정상'} — 최대 {top[0]} z {top[1]:+.2f} (기준 ±{th})"


def _news_line(name: str, news: dict | None, min_points: int) -> str:
    if not news:
        return f"**{name}**: ⚪ 데이터 없음"
    clusters = news.get("clusters") or []
    if clusters:
        tops = ", ".join(f"{c['event_type']}({c.get('n_sources', '?')}곳)" for c in clusters[:3])
        return f"**{name}**: 🔴 기사량 급증 {tops}"
    status = news.get("status", "ok")
    if status == "unavailable":
        pts = [o.get("baseline_points") for o in (news.get("observations") or {}).values() if o.get("baseline_points") is not None]
        if pts and min(pts) < min_points:
            return f"**{name}**: ⚪ 판단 불가 — 기준선 축적 중 {min(pts)}/{min_points} (‘사건 없음’이 확인된 건 아님)"
        return f"**{name}**: ⚪ 판단 불가 — 조회 실패"
    if status == "partial":
        return f"**{name}**: 🟢 판단된 주제에서는 급증 없음 (일부 주제 판단 불가)"
    return f"**{name}**: 🟢 급증 없음"


def _next_step(level: str, news: dict | None) -> str:
    if level == "ALERT":
        return "→ **할 일**: 대응안 브리핑을 확인하고 승인 탭에서 결정"
    if level == "WATCH":
        return "→ **할 일**: 사건 확인 전까지 감시 유지 (자동 대응안은 ALERT에서만) · 지금 보려면 브리핑 탭 ▶ 지금 브리핑 실행"
    if news and news.get("status") == "unavailable":
        return "→ **할 일**: 없음. 사건 판단은 기준선이 차면 시작 · 지금 보려면 브리핑 탭 ▶ 지금 브리핑 실행"
    return "→ **할 일**: 없음 · 지금 보려면 브리핑 탭 ▶ 지금 브리핑 실행"


def watch_local(loc: dict) -> Summary:
    th = load_config()["korea"]["thresholds"]
    min_points = load_config()["korea"]["news"]["baseline_min_points"]
    level = loc.get("level", "NONE")
    mk, fl = loc.get("kr_market") or {}, loc.get("kr_flow") or {}
    bullets = [
        _signal_line("한국 시장(A)", mk.get("zscores", {}), mk.get("triggered", []), th["market_z"]),
        _signal_line("외국인 자금(C)", fl.get("zscores", {}), fl.get("triggered", []), th["flow_z"]),
        _news_line("한국 사건(B)", loc.get("kr_news"), min_points),
    ]
    warns = loc.get("warnings") or []
    if warns:
        bullets.append(f"**DART 공시**: 🟠 신용 경고 {len(warns)}건 ({', '.join(w['corp_name'] for w in warns[:3])})")
    if loc.get("money_alert"):
        bullets.append("**1단계 자금 이상 알림**: 🟠 발동 (5영업일 중 지속 기준 충족)")
    bullets.append(_next_step(level, loc.get("kr_news")))
    return Summary(LEVEL_TONE.get(level, "gray"), f"로컬 등급 {LEVEL_KO.get(level, level)} · 기준 {loc.get('as_of', '-')} KST", bullets)


def watch_global(sig: dict) -> Summary:
    cfg = load_config()["sentinel"]
    level = sig.get("level", "NONE")
    flow = sig.get("flow") or {}
    bullets = [
        _signal_line("시장(A)", sig["market"].get("zscores", {}), sig["market"].get("triggered", []), cfg["market"]["z_threshold"]),
        _signal_line("자금 흐름(C)", flow.get("zscores", {}), flow.get("triggered", []), cfg["flow"]["z_threshold"]),
        _news_line("사건(B, 뉴스)", sig.get("news"), cfg["news"]["baseline_min_points"]),
    ]
    if sig.get("money_alert"):
        bullets.append("**1단계 자금 이상 알림**: 🟠 발동")
    bullets.append(_next_step(level, sig.get("news")))
    return Summary(LEVEL_TONE.get(level, "gray"), f"글로벌 등급 {LEVEL_KO.get(level, level)} · 기준일 {sig.get('as_of', '-')}", bullets)


def watch_replay(df: pd.DataFrame, event_title: str, event_date) -> Summary:
    first_alert = df[df["등급"] == "ALERT"]["날짜"].min()
    money = df[(df["날짜"] < event_date) & df["자금 이상 알림"]]["날짜"]
    bullets = [f"**사건일**: {event_date}",
               f"**사건 전 자금 이상 알림**: {len(money)}일" + (f" (첫 알림 {money.min()}, {(event_date - money.min()).days}일 전)" if len(money) else ""),
               f"**첫 ALERT(대응안)**: {first_alert if pd.notna(first_alert) else '없음'}"]
    tone = "red" if pd.notna(first_alert) else ("orange" if len(money) else "gray")
    return Summary(tone, f"재생: {event_title}", bullets)


def briefing(b: Any, kind: str = "auto") -> Summary:
    """kind: auto(자동 감시 사건) / ondemand(직접 실행) / scenario(가정 사건)."""
    level = b.alert_level.value
    fits = b.match.doc_fits
    bullets = []
    if fits:
        top = fits[0]
        bullets.append(f"**1위 문서**: {top.doc_id} 적합도 {top.fit_score:.2f} (적용 {top.n_applicable} · 부분 {top.n_partial})"
                       + (f" · 2위 {fits[1].doc_id} {fits[1].fit_score:.2f}" if len(fits) > 1 else ""))
    else:
        bullets.append("**문서**: 판정된 문서 없음")
    gaps = [g.value for g in b.match.gaps]
    bullets.append(f"**대응 공백 채널**: {'🔴 ' + ', '.join(gaps) if gaps else '🟢 없음'}")
    if b.exposure_entities:
        bullets.append(f"**동일 발행자 보유**: 🔴 {', '.join(p.nodes[-2] for p in b.exposure_entities[:3])}")
    if b.exposure_top:
        p = b.exposure_top[0]
        bullets.append(f"**가장 큰 노출**: {' → '.join(p.nodes[1:])} (비중 {p.weight:.1%}, risk {p.risk_score:.3f})")
    elif b.exposure_note:
        bullets.append(f"**노출**: {b.exposure_note[:80]}")
    roles = {a.partition('] ')[0].lstrip('[') for a in b.actions_to_check if '] ' in a}
    bullets.append(f"**확인 항목**: {len(b.actions_to_check)}개 · 담당 {len(roles)}곳")
    if b.match.low_confidence:
        bullets.append("⚠️ 판정 평균 신뢰도 낮음 — 사람 확인 필요")
    bullets.append("→ **할 일**: 아래 1위 문서 조항과 확인 항목 검토 후 승인 탭에서 결정")
    prefix = {"scenario": "🧪 가정 시나리오 · ", "ondemand": "▶ 직접 실행 · "}.get(kind, "")
    head = prefix + (b.event.title if kind == "ondemand" else f"{LEVEL_KO.get(level, level)} · {b.event.title}")
    return Summary("blue" if kind != "auto" else LEVEL_TONE.get(level, "gray"), head, bullets)


def approval(b: Any, records: list[dict]) -> Summary:
    mine = [r for r in records if r.get("data", {}).get("run_id") == b.run_id]
    decisions = [r for r in mine if r["action"] == "approval"]
    fb = [r for r in mine if r["action"] == "feedback"]
    last = decisions[-1] if decisions else None
    if last:
        d = last["data"]["decision"]
        tone, head = ("green", "승인 완료") if d == "approved" else ("orange", "반려")
        head += f" · {last['actor']} · {last['ts'][:16].replace('T', ' ')} UTC"
    else:
        tone, head = "gray", "승인 대기"
    useful = sum(r["data"].get("label") == "useful" for r in fb)
    bullets = [f"**브리핑**: {b.event.title} (run {b.run_id})",
               f"**문서 피드백**: {len(fb)}건 (유용 {useful} · 부적합 {len(fb) - useful})",
               "→ **할 일**: " + ("없음 (결정 기록됨, 감사 로그에 남음)" if last else "문서별 유용/부적합 표시 후 승인 또는 반려")]
    return Summary(tone, head, bullets)


def learner(enabled: bool, docs: list[dict], delta: float | None) -> Summary:
    cited = sum(d.get("cited") or 0 for d in docs)
    useful = sum(d.get("useful") or 0 for d in docs)
    bullets = [f"**기록**: 문서 {len(docs)}개 · 인용 {cited}회 · 유용 피드백 {useful}건",
               f"**ON/OFF 효과 (시뮬레이션)**: top3 적중 차이 {delta if delta is not None else '-'}"
               + (" — 이력이 쌓이기 전에는 순위 변화 없음 (설계 의도)" if not delta else "")]
    top = sorted(docs, key=lambda d: -(d.get("useful") or 0))[:3]
    if top and useful:
        bullets.append("**유용 피드백 상위**: " + ", ".join(f"{d['doc_id']}({d['useful']})" for d in top if d.get("useful")))
    bullets.append("→ 문서는 삭제·폐기하지 않는다. protected 문서는 항상 후보")
    return Summary("blue" if enabled else "gray", f"학습 층 {'ON' if enabled else 'OFF'}", bullets)


def data_input(portfolio: Any, holdings: list[dict] | None, playbooks: list | None) -> Summary:
    bullets = []
    if portfolio is not None:
        n = len(holdings or [])
        bullets.append(f"**포트폴리오**: 🟢 {portfolio.institution} · 종목 {n}개 반영 중")
    else:
        bullets.append("**포트폴리오**: ⚪ 기본(합성) 사용 중 — 엑셀·CSV를 올리면 노출 분석에 반영")
    if playbooks:
        bullets.append(f"**대응 문서**: 🟢 업로드 {len(playbooks)}개 · 조항 {sum(len(p.clauses) for p in playbooks)}개 반영 중")
    else:
        bullets.append("**대응 문서**: ⚪ 기본(합성 12개) 사용 중 — PDF·워드를 올리면 조항으로 분해해 반영")
    bullets.append("→ 보유 종목명은 외부 LLM에 보내지 않는다 (표 구조 요약만 전송, 끌 수 있음)")
    tone = "green" if portfolio is not None or playbooks else "gray"
    return Summary(tone, "업로드 데이터 반영 상태", bullets)


# ---------- 그래프 ----------


def _y(field: str, sort: Any = None) -> alt.Y:
    """가로 막대 범주축: 이름을 건너뛰지 않게."""
    return alt.Y(field, sort=sort, title=None, axis=alt.Axis(labelOverlap=False, labelLimit=240))


def _bar_base(df: pd.DataFrame) -> alt.Chart:
    return alt.Chart(df).mark_bar(cornerRadiusEnd=4)


def z_chart(zscores: dict[str, float | None], threshold: float, title: str) -> alt.Chart | None:
    """지표별 z 막대 + ±임계선. 임계에 얼마나 가까운지 한눈에 (0.75×임계부터 주의)."""
    rows = [{"지표": k, "z": v} for k, v in (zscores or {}).items() if v is not None]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["상태"] = df["z"].abs().map(lambda a: "임계 초과" if a >= threshold else ("임계 근접" if a >= 0.75 * threshold else "정상"))
    lim = max(threshold * 1.25, float(df["z"].abs().max()) * 1.1)
    color = alt.Color("상태:N", scale=alt.Scale(domain=["정상", "임계 근접", "임계 초과"], range=[BLUE_LIGHT, WARNING, CRITICAL]),
                      legend=alt.Legend(orient="bottom", title=None))
    bars = _bar_base(df).encode(
        x=alt.X("z:Q", scale=alt.Scale(domain=[-lim, lim]), title="z-score"),
        y=_y("지표:N"), color=color,
        tooltip=["지표", alt.Tooltip("z:Q", format="+.2f"), "상태"])
    rules = alt.Chart(pd.DataFrame({"x": [-threshold, threshold]})).mark_rule(strokeDash=[4, 4], color=MUTED).encode(x="x:Q")
    return (bars + rules).properties(title=f"{title} (점선 = 임계 ±{threshold})", height=_h(len(df)))


def news_chart(observations: dict[str, dict], z_threshold: float, title: str) -> alt.Chart | None:
    """주제별 최근 24시간 기사 수. 색 = 판단 상태 (기준선 축적 중이면 회색)."""
    if not observations:
        return None
    rows = []
    for k, o in observations.items():
        z = o.get("z")
        state = "판단 불가(기준선 축적)" if z is None else ("급증" if z >= z_threshold else "평소 수준")
        rows.append({"주제": k, "기사 수": o.get("n_articles", 0), "언론사": o.get("n_sources", 0),
                     "z": None if z is None else round(z, 2), "상태": state, "기준점": o.get("baseline_points")})
    df = pd.DataFrame(rows).sort_values("기사 수", ascending=False)
    color = alt.Color("상태:N", scale=alt.Scale(domain=["평소 수준", "급증", "판단 불가(기준선 축적)"], range=[BLUE, CRITICAL, NEUTRAL]),
                      legend=alt.Legend(orient="bottom", title=None))
    return _bar_base(df).encode(
        x=alt.X("기사 수:Q", title="최근 24시간 기사 수"), y=_y("주제:N", "-x"), color=color,
        tooltip=["주제", "기사 수", "언론사", "z", "기준점", "상태"]).properties(title=title, height=_h(len(df), 28))


def fit_chart(doc_fits: list, top: int = 8) -> alt.Chart | None:
    """문서별 조항 판정 누적 막대 (순위순). 적합도 = (적용 + 0.5×부분) / 판정 조항."""
    rows = []
    for rank, f in enumerate(doc_fits[:top], start=1):
        label = f"{rank}. {f.doc_id} ({f.fit_score:.2f})"
        for k, n in (("적용", f.n_applicable), ("부분", f.n_partial), ("부적용", f.n_not), ("불확실", f.n_uncertain)):
            if n:
                rows.append({"문서": label, "판정": k, "조항 수": n, "order": list(VERDICT_COLOR).index(k)})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    order = [f"{i}. {f.doc_id} ({f.fit_score:.2f})" for i, f in enumerate(doc_fits[:top], start=1)]
    return _bar_base(df).encode(
        x=alt.X("sum(조항 수):Q", title="판정 조항 수", stack="zero"),
        y=_y("문서:N", order),
        color=alt.Color("판정:N", scale=alt.Scale(domain=list(VERDICT_COLOR), range=list(VERDICT_COLOR.values())),
                        legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("order:Q"), tooltip=["문서", "판정", "조항 수"],
    ).properties(title="문서별 적합도 (괄호 = 적합도, 위가 1위)", height=_h(len(order)))


def exposure_chart(paths: list, top: int = 8) -> alt.Chart | None:
    if not paths:
        return None
    df = pd.DataFrame([{"경로": " → ".join(p.nodes[1:])[-48:], "risk_score": p.risk_score, "비중": p.weight,
                        "불확실성": p.uncertainty} for p in paths[:top]])
    return _bar_base(df).encode(
        x=alt.X("risk_score:Q", title="risk score (비중 × 연관도 × 불확실성 감점)"),
        y=_y("경로:N", "-x"), color=alt.value(BLUE),
        tooltip=["경로", alt.Tooltip("risk_score:Q", format=".4f"), alt.Tooltip("비중:Q", format=".2%"), "불확실성"],
    ).properties(title="보유 자산 노출 상위 경로", height=_h(len(df)))


def actions_chart(actions: list[str]) -> alt.Chart | None:
    roles = Counter(a.partition("] ")[0].lstrip("[") if "] " in a else "기타" for a in actions)
    if not roles:
        return None
    df = pd.DataFrame([{"담당": k, "확인 항목": v} for k, v in roles.items()])
    return _bar_base(df).encode(x=alt.X("확인 항목:Q", title="확인 항목 수"), y=_y("담당:N", "-x"),
                                color=alt.value(BLUE), tooltip=["담당", "확인 항목"]
                                ).properties(title="담당별 확인 항목", height=_h(len(df)))


def capture_chart(v6: dict) -> alt.Chart | None:
    """사건 포착률 vs 같은 규칙으로 무작위 날짜를 찍었을 때의 우연 포착률."""
    rows = []
    for scope, label in (("global", "글로벌"), ("local_kr", "한국")):
        s = v6.get(scope) or {}
        r = s.get("adopted_full_period") or s.get("current_full_period")
        if r:
            rows += [{"범위": label, "구분": "실제 포착", "비율": r["caught_rate"], "p": r["p_value_caught"]},
                     {"범위": label, "구분": "우연 기대", "비율": r["base_rate_caught"], "p": r["p_value_caught"]}]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return alt.Chart(df).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("비율:Q", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, 1]), title=None),
        y=alt.Y("구분:N", title=None, sort=["실제 포착", "우연 기대"]), row=alt.Row("범위:N", title=None),
        color=alt.Color("구분:N", scale=alt.Scale(domain=["실제 포착", "우연 기대"], range=[BLUE, ORANGE]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["범위", "구분", alt.Tooltip("비율:Q", format=".0%"), alt.Tooltip("p:Q", format=".4f")],
    ).properties(title="사건 23개 포착률 vs 우연 (사전 등록 v6)", height=70)


def lead_chart(v6: dict) -> alt.Chart | None:
    g = (v6.get("global") or {})
    r = g.get("adopted_full_period") or g.get("current_full_period")
    if not r:
        return None
    df = pd.DataFrame([{"사건": e["id"], "날짜": e["date"], "선행일": e.get("lead_days") or 0,
                        "결과": "사전 알림" if e.get("prior_warning") else ("사건 후 포착" if e.get("caught") else "놓침")}
                       for e in r["events"]])
    order = df.sort_values("날짜")["사건"].tolist()  # 두 층이 같은 시간순 축을 쓰게 명시
    x = alt.X("사건:N", sort=order, scale=alt.Scale(domain=order), title=None, axis=alt.Axis(labelAngle=-45, labelOverlap=False))
    scale = alt.Scale(domain=["사전 알림", "사건 후 포착", "놓침"], range=[BLUE, BLUE_LIGHT, NEUTRAL])
    color = alt.Color("결과:N", scale=scale, legend=alt.Legend(orient="bottom", title=None))
    tip = ["사건", "날짜", "선행일", "결과"]
    bars = alt.Chart(df[df["결과"] == "사전 알림"]).mark_bar(cornerRadiusEnd=4).encode(
        x=x, y=alt.Y("선행일:Q", title="사건 전 첫 알림 (일)"), color=color, tooltip=tip)
    # 선행일 0인 사건(사건 후 포착·놓침)도 보이게 기준선 위 점으로 표시
    dots = alt.Chart(df[df["결과"] != "사전 알림"]).mark_point(filled=True, size=90).encode(
        x=x, y=alt.datum(0), color=alt.Color("결과:N", scale=scale, legend=None), shape=alt.Shape("결과:N", legend=None), tooltip=tip)
    return (bars + dots).properties(title="글로벌 사건별 선행일 (막대 = 사전 알림, 점 = 사건 후 포착·놓침)", height=340)


def confusion_chart(confusion: dict[str, int]) -> alt.Chart | None:
    if not confusion:
        return None
    rows = []
    for k, n in confusion.items():
        a, b = k.split("→")
        rows.append({"정답(라벨)": VERDICT_KO.get(a, a), "에이전트": VERDICT_KO.get(b, b), "건수": n, "일치": a == b})
    df = pd.DataFrame(rows)
    order = ["적용", "부분", "부적용"]
    base = alt.Chart(df).encode(x=alt.X("에이전트:N", sort=order, axis=alt.Axis(labelAngle=0, orient="top")),
                                y=alt.Y("정답(라벨):N", sort=order))
    heat = base.mark_rect(cornerRadius=4).encode(
        color=alt.Color("건수:Q", scale=alt.Scale(range=["#cde2fb", "#184f95"]), legend=None),
        tooltip=["정답(라벨)", "에이전트", "건수"])
    text = base.mark_text(fontSize=13).encode(
        text="건수:Q", color=alt.condition(alt.datum.건수 > 40, alt.value("#ffffff"), alt.value("#0b0b0b")))
    return (heat + text).properties(title="조항 판정 혼동행렬 (대각선 = 일치)", height=320)


def priority_chart(docs: list[dict]) -> alt.Chart | None:
    rows = []
    for d in docs:
        for k, label in (("useful", "유용"), ("not_fit", "부적합")):
            if d.get(k):
                rows.append({"문서": d["doc_id"], "피드백": label, "건수": d[k]})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    return _bar_base(df).encode(
        x=alt.X("sum(건수):Q", title="피드백 건수"), y=_y("문서:N", "-x"),
        color=alt.Color("피드백:N", scale=alt.Scale(domain=["유용", "부적합"], range=[GOOD, NEUTRAL]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["문서", "피드백", "건수"]).properties(title="문서별 피드백 (학습 층 입력)", height=_h(df["문서"].nunique()))


def weight_chart(holdings: pd.DataFrame, by: str, title: str, top: int = 10) -> alt.Chart | None:
    if holdings is None or holdings.empty or by not in holdings or "weight" not in holdings:
        return None
    s = holdings.groupby(holdings[by].fillna("미상"))["weight"].sum().sort_values(ascending=False)
    df = pd.DataFrame({by: s.index[:top], "비중": s.values[:top]})
    if len(s) > top:
        df.loc[len(df)] = {by: "기타", "비중": float(s.values[top:].sum())}
    return _bar_base(df).encode(
        x=alt.X("비중:Q", axis=alt.Axis(format="%"), title=None), y=_y(f"{by}:N"),
        color=alt.value(BLUE), tooltip=[by, alt.Tooltip("비중:Q", format=".2%")]
    ).properties(title=title, height=_h(len(df), 28))


def country_chart(values: dict[str, float] | None, title: str, fmt: str = ".1%", top: int = 10) -> alt.Chart | None:
    if not values:
        return None
    s = pd.Series(values).sort_values(ascending=False)
    df = pd.DataFrame({"국가": s.index[:top], "값": s.values[:top]})
    return _bar_base(df).encode(
        x=alt.X("값:Q", axis=alt.Axis(format=fmt), title=None), y=_y("국가:N"),
        color=alt.value(BLUE), tooltip=["국가", alt.Tooltip("값:Q", format=fmt)]
    ).properties(title=title, height=_h(len(df), 28))
