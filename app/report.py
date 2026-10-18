"""대응안 리포트 (Markdown). 모든 절은 원인 → 근거 → 결과 순서로 쓴다."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.schemas import Briefing, Verdict

VERDICT = {Verdict.applicable: "적용", Verdict.partial: "부분적용", Verdict.not_applicable: "부적용", Verdict.uncertain: "불확실"}


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def chain_table(chain: list[dict[str, str]]) -> list[str]:
    lines = ["| 단계 | 원인 | 근거 | 결과 |", "|---|---|---|---|"]
    lines += [f"| {_cell(c['단계'])} | {_cell(c['원인'])} | {_cell(c['근거'])} | {_cell(c['결과'])} |" for c in chain]
    return lines


def build_report(title: str, as_of: datetime, chain: list[dict[str, str]], linkage: dict | None = None,
                 briefing: Briefing | None = None, clause_text: dict[str, str] | None = None) -> str:
    clause_text = clause_text or {}
    final = chain[-1] if chain else {"결과": "-"}
    md = [f"# {title}", "", f"- 작성: {as_of:%Y-%m-%d %H:%M %Z} · Alpha Sunset (에이전트 제안, 최종 결정은 사람)",
          f"- **결론**: {final['결과']}", "", "## 1. 경보 판단 (원인 → 근거 → 결과)", ""]
    md += chain_table(chain)

    if linkage:
        md += ["", "## 2. 해외-한국 연관성 근거", "",
               f"- 원인(동시 반응): 해외 {linkage['co_movement']['global'] or '-'} / 한국 {linkage['co_movement']['korea'] or '-'}",
               "- 근거(과거 연동성, 기준일 전날까지 1년 일변화 상관):", "", "| 쌍 | 상관계수 | 최근 5년 분위 | 비고 |", "|---|---|---|---|"]
        md += [f"| {x['pair']} | {x['corr'] if x['corr'] is not None else '-'} | {x['percentile'] if x['percentile'] is not None else '-'} | {x['note']} |"
               for x in linkage["historical_link"]]
        exp = linkage["exposure_link"]
        md += ["", f"- 근거(노출 경로): 한국 노출 비중 {exp['kr_weight'] if exp['kr_weight'] is not None else '-'}, 영향도 {exp['kr_impact'] if exp['kr_impact'] is not None else '-'}",
               f"- 결과: **{'연관 근거 약함' if linkage['weak'] else '연관 근거 있음'}** — {linkage['caveat']}"]

    if briefing:
        e = briefing.event
        md += ["", "## 3. 사건", "", f"- {e.title} ({e.date}) · 유형 {e.type.value} · 심각도 {e.severity}/5 · 지역 {', '.join(e.regions)}",
               f"- 요약: {e.summary}", "", "## 4. 대응문서 적합도 (원인 → 근거 → 결과)", ""]
        for f in briefing.match.doc_fits[:3]:
            md += [f"### {f.doc_id} — 적합도 {f.fit_score:.2f} (적용 {f.n_applicable} · 부분 {f.n_partial} · 부적용 {f.n_not} · 불확실 {f.n_uncertain})", "",
                   "| 조항 | 원인(조항 전제) | 근거(인용) | 결과 |", "|---|---|---|---|"]
            for j in f.judgments:
                reason = "; ".join(j.mismatch_reasons) or _cell(clause_text.get(j.clause_id, ""))[:80]
                md.append(f"| {j.clause_id} | {_cell(reason)} | {_cell(j.evidence_quote) or '-'} | {VERDICT[j.verdict]} (신뢰도 {j.confidence:.2f}) |")
            md.append("")
        md += ["## 5. 공백 채널", "", ("- " + ", ".join(g.value for g in briefing.match.gaps)) if briefing.match.gaps else "- 없음",
               "", "## 6. 보유 노출 상위 경로 (원인 → 근거 → 결과)", "", "| 경로 | 근거 | risk |", "|---|---|---|"]
        md += [f"| {_cell(' → '.join(p.nodes[1:]))} | {_cell(p.why)} | {p.risk_score:.4f} |" for p in briefing.exposure_top[:5]]
        if briefing.exposure_note:
            md += ["", f"- 비고: {briefing.exposure_note}"]
        md += ["", "## 7. 담당별 확인 항목", ""] + [f"- [ ] {a}" for a in briefing.actions_to_check]
        if briefing.evidence_refs:
            md += ["", "## 8. 출처", ""] + [f"- {r}" for r in briefing.evidence_refs]
    md += ["", "---", "※ 대응문서·포트폴리오는 합성 데이터다. 수치는 공개 데이터(FRED·ECOS·DART·뉴스)의 기준 시각 값이다.", ""]
    return "\n".join(md)


def save_report(text: str, out_dir: Path, name: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path
