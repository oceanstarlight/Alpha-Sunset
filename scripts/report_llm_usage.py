"""LLM API 사용 내역 보고서 (llm_calls 테이블) → docs/API_USAGE.md.

운영진 사용 내역 요청 대비. 배포 환경 DB는 재시작 시 초기화되므로 개발 환경 기록을 주기적으로 남긴다.
사용: python -m scripts.report_llm_usage
"""

from __future__ import annotations

import sqlite3
from datetime import date

from app.config import ROOT_DIR, get_settings

OUT = ROOT_DIR / "docs" / "API_USAGE.md"


def main() -> None:
    s = get_settings()
    lines = ["# LLM API 사용 내역", "", f"> 생성일 {date.today()} · 출처 `llm_calls` 테이블 (모든 호출은 `app/llm/client.py` 단일 래퍼 경유)",
             "> 캐시 적중(cache_hit=1)은 실제 API 호출 없이 저장된 응답을 재사용한 건이다.", ""]
    for name, path in (("백테스트·개발 (sandbox.db)", s.sandbox_db), ("라이브 (live.db)", s.live_db)):
        if not path.exists():
            lines += [f"## {name}", "", "기록 없음", ""]
            continue
        c = sqlite3.connect(path)
        total = c.execute("SELECT COUNT(*), SUM(cache_hit), SUM(in_tokens), SUM(out_tokens), MIN(ts), MAX(ts) FROM llm_calls").fetchone()
        lines += [f"## {name}", ""]
        if not total[0]:
            lines += ["기록 없음", ""]
            continue
        n, hit, tin, tout, t0, t1 = total
        lines += [f"- 기간: {t0[:19]} ~ {t1[:19]} (UTC)",
                  f"- 전체 {n}건 = 실제 API 호출 {n - hit}건 + 캐시 적중 {hit}건",
                  f"- 토큰: 입력 {tin:,} / 출력 {tout:,} (임베딩은 토큰 수 미제공)", "",
                  "| 모델 | 용도 | 실제 호출 | 캐시 적중 | 입력 토큰 | 출력 토큰 |", "|---|---|---|---|---|---|"]
        for row in c.execute("SELECT model, purpose, SUM(1 - cache_hit), SUM(cache_hit), SUM(in_tokens), SUM(out_tokens) "
                             "FROM llm_calls GROUP BY model, purpose ORDER BY model, purpose"):
            lines.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]:,} | {row[5]:,} |")
        lines.append("")
        c.close()
    lines += ["## 비용", "", "Gemini API 무료 등급만 사용 (분당 15회 제한에 맞춰 요청 간격 조절). 유료 과금 없음."]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
