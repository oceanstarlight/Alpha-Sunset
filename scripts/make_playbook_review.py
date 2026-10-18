"""플레이북 사람 검수용 시트 → docs/PLAYBOOK_REVIEW.md.

에이전트 판정 결과는 넣지 않는다 (검수가 결과에 끌려가지 않도록). 자동 점검 항목은 참고용 표시다.
사용: python -m scripts.make_playbook_review
"""

from __future__ import annotations

from collections import Counter

from app.config import ROOT_DIR
from app.corpus import load_playbooks

OUT = ROOT_DIR / "docs" / "PLAYBOOK_REVIEW.md"
ORIGIN_TYPE = {"gfc_2008": "credit_event", "covid_2020": "pandemic", "ru_ua_2022": "geopolitical", "legoland_2022": "liquidity_crisis",
               "svb_2023": "banking_stress", "tariff_2025": "trade_policy", "rate_hike_2022": "rate_shock"}


def flags(clause, doc, dup_texts) -> list[str]:
    out = []
    p = clause.premises
    if not p.event_types and not clause.protected:
        out.append("전제 사건유형 없음")
    if not p.channels and not clause.protected:
        out.append("전제 채널 없음")
    origin = ORIGIN_TYPE.get(doc.origin_event)
    if origin and p.event_types and origin not in [t.value for t in p.event_types]:
        out.append(f"원 사건 유형({origin})이 전제에 없음")
    if clause.text in dup_texts:
        out.append("다른 조항과 문구 중복(의도된 중복인지 확인)")
    return out


def main() -> None:
    pbs = load_playbooks()
    texts = Counter(c.text for p in pbs for c in p.clauses)
    dup = {t for t, n in texts.items() if n > 1}
    n_flag = 0
    body = []
    for p in pbs:
        body += ["", f"## {p.doc_id} · {p.title}", f"v{p.version} · {p.year}년 · 원 사건 `{p.origin_event}` · 근거 {', '.join(p.source_refs)}", "",
                 "| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |",
                 "|---|---|---|---|---|---|---|---|"]
        for c in p.clauses:
            pr = c.premises
            premise = " / ".join([", ".join(t.value for t in pr.event_types) or "-", ", ".join(x.value for x in pr.channels) or "-",
                                  ", ".join(pr.regions) or "-", "; ".join(pr.conditions) or "-"])
            f = flags(c, p, dup)
            n_flag += bool(f)
            body.append(f"| `{c.clause_id}`{' 🔒' + (c.protected_reason or '') if c.protected else ''} | {c.text} | {premise} | "
                        f"{'; '.join(c.actions)} | {c.owner_role} | {'⚠️ ' + ', '.join(f) if f else ''} |  |  |")
    head = ["# 플레이북 검수 시트", "",
            "> 합성 대응문서 12개·96조항 (Claude 초안). 실무자 관점에서 현실성·일관성을 검수한다.",
            "> **에이전트 판정 결과(`data/backtest/`, 데모 브리핑 탭)는 보지 말고 검수한다.** 결과를 좋게 만들려고 고치면 그것도 편향이다.", "",
            "## 검수 기준 (조항마다)",
            "1. **현실성**: 실제 기관투자자 위기 대응 매뉴얼에 있을 법한 조항인가",
            "2. **전제 정확성**: 전제(사건유형·채널·지역·조건)가 조항 내용과 맞는가. 너무 넓거나 좁지 않은가",
            "3. **조치 구체성**: 조치가 실행 가능한 수준으로 구체적인가",
            "4. **담당 적절성**: 담당 부서가 맞는가",
            "5. **protected(🔒)**: 규제 필수·보험형이 맞는가",
            "", "## 작성 방법",
            "- '검수' 칸에 OK / 수정 / 삭제, '의견' 칸에 수정 내용을 적는다. 또는 채팅으로 `PB-LIQ-03: 조치를 ○○로` 처럼 알려줘도 된다.",
            "- 의도된 설계: 문서는 원 사건 전제에 묶여 있어 다른 사건엔 일부만 맞아야 하고, 일부러 오래된 문서(PB-FX·PB-CPTY 2009년)와 중복 조항(현금성 자산 보충 등)을 넣었다.",
            "- 조항 ID는 라벨이 참조하므로 **삭제·ID 변경 시 알려줘야 한다** (라벨 정리 필요).",
            "- 수정 반영 후에는 판정·노출·브리핑·지표를 전부 다시 계산한다 (Gemini 재호출).", "",
            f"자동 점검 표시 조항: {n_flag}개 (참고용, 문제라는 뜻은 아님)"]
    OUT.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT_DIR)} · 자동 점검 표시 {n_flag}개")


if __name__ == "__main__":
    main()
