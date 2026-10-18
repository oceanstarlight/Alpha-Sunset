# LLM API 사용 내역

> 생성일 2026-10-18 · 출처 `llm_calls` 테이블 (모든 호출은 `app/llm/client.py` 단일 래퍼 경유)
> 캐시 적중(cache_hit=1)은 실제 API 호출 없이 저장된 응답을 재사용한 건이다.

## 백테스트·개발 (sandbox.db)

- 기간: 2026-10-18T04:30:19 ~ 2026-10-18T08:28:31 (UTC)
- 전체 998건 = 실제 API 호출 304건 + 캐시 적중 694건
- 토큰: 입력 342,635 / 출력 127,330 (임베딩은 토큰 수 미제공)

| 모델 | 용도 | 실제 호출 | 캐시 적중 | 입력 토큰 | 출력 토큰 |
|---|---|---|---|---|---|
| gemini-3.5-flash-lite | clean_actions | 18 | 14 | 12,967 | 12,892 |
| gemini-3.5-flash-lite | exposure_entity_match | 12 | 16 | 21,739 | 332 |
| gemini-3.5-flash-lite | exposure_why | 12 | 40 | 15,781 | 6,319 |
| gemini-3.5-flash-lite | judge_clauses | 133 | 421 | 192,104 | 103,925 |
| gemini-3.5-flash-lite | orchestrator | 104 | 127 | 97,011 | 1,102 |
| gemini-3.5-flash-lite | structure_event | 12 | 12 | 3,033 | 2,760 |
| gemini-embedding-001 | index_clauses | 1 | 7 | 0 | 0 |
| gemini-embedding-001 | retrieve_clauses | 12 | 57 | 0 | 0 |

## 라이브 (live.db)

기록 없음

## 비용

Gemini API 무료 등급만 사용 (분당 15회 제한에 맞춰 요청 간격 조절). 유료 과금 없음.
