"""P4 Matcher 재생: 6개 사건 MatchResult 생성.

LLM 호출은 sandbox DB에 기록되고 응답은 data/llm_cache.db에 캐시된다 (커밋하면 키 없이 재현 가능).
결과: data/backtest/match/{event_id}.json, data/backtest/match_summary.json
사용: python -m scripts.run_matcher [--event svb_2023]
"""

from __future__ import annotations

import argparse
import json

from app.agents.matcher import match, verify_card
from app.config import ROOT_DIR
from app.corpus import load_events, load_playbooks
from app.llm.client import LLMClient
from app.retrieval import ClauseIndex
from app.schemas import Verdict

OUT_DIR = ROOT_DIR / "data" / "backtest" / "match"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="특정 사건만 실행")
    args = parser.parse_args()

    llm = LLMClient(db_mode="sandbox")
    index = ClauseIndex(load_playbooks(), llm)
    events = [e for e in load_events() if not args.event or e.id == args.event]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = []
    for e in sorted((e.as_of_view() for e in events), key=lambda e: e.date):  # 사건일 시점 정보만
        card_check = verify_card(llm, e)
        result = match(e, index, llm)
        (OUT_DIR / f"{e.id}.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")

        judgments = [j for f in result.doc_fits for j in f.judgments]
        no_evidence = sum(j.verdict != Verdict.uncertain and not j.evidence_quote.strip() for j in judgments)
        row = {
            "event_id": e.id,
            "n_judged": len(judgments),
            "verdicts": {v.value: sum(j.verdict == v for j in judgments) for v in Verdict},
            "no_evidence_judgments": no_evidence,
            "top3": [(f.doc_id, f.fit_score) for f in result.doc_fits[:3]],
            "gaps": [g.value for g in result.gaps],
            "low_confidence": result.low_confidence,
            "card_check": card_check,
        }
        summary.append(row)
        top = ", ".join(f"{d}({s:.2f})" for d, s in row["top3"])
        print(f"{e.id:14s} 판정 {row['n_judged']:3d} {row['verdicts']}  근거없음 {no_evidence}  top3: {top}  공백: {row['gaps']}  "
              f"카드검증 type={card_check['type_match']} ch={card_check['channel_jaccard']}")

    if not args.event:
        (ROOT_DIR / "data" / "backtest" / "match_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
