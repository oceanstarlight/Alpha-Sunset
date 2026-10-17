# Current — 진행 현황

> 기준 문서: [`plans.md`](./plans.md) · Phase 번호 = plans.md 9장 마일스톤 번호(M0~M10)
> 마지막 갱신: 2026-10-17

## 범례
| 표시 | 의미 |
|---|---|
| ✅ | 완료 |
| 🔄 | 진행 중 |
| ⏳ | 예정 |
| ⏸️ | 보류 |
| 🗑️ | 폐기 |

## 한눈에 보기
| Phase | 내용 | 상태 |
|---|---|---|
| Phase 0 | 스캐폴딩 | ⏳ 예정 |
| Phase 1 | 외부 데이터 수집 | ⏳ 예정 |
| Phase 2 | 합성 코퍼스 | ⏳ 예정 |
| Phase 3 | Sentinel (상시 감시) | ⏳ 예정 |
| Phase 4 | Matcher (적합도 판단) | ⏳ 예정 |
| Phase 5 | Exposure (노출 경고) | ⏳ 예정 |
| Phase 6 | Orchestrator + Briefing | ⏳ 예정 |
| Phase 7 | 서비스 계층 + UI + 배포 | ⏳ 예정 |
| Phase 8 | 백테스트 | ⏳ 예정 |
| Phase 9 | Learner (알파 썬셋) | ⏳ 예정 |
| Phase 10 | 제출물 | ⏳ 예정 |

---

## Phase 0 — 스캐폴딩 ⏳
- ⏳ 디렉터리 구조 생성 (plans.md 2장)
- ⏳ `config.yaml`, `.env.example`, `requirements.txt`(버전 고정)
- ⏳ `app/schemas.py` — Enum·모델 전체 (plans.md 3장)
- ⏳ `app/db.py` — `live.db` / `sandbox.db` 분리
- ⏳ `app/llm/client.py` 단일 래퍼 + `llm/cache.py` + `llm_calls` 로깅
- ⏳ 테스트 틀: 스키마 round-trip, 근거 없는 verdict 거부, live/sandbox 분리
- **완료 기준**: `pytest` 통과, LLM 호출이 `llm_calls`에 기록됨

## Phase 1 — 외부 데이터 수집 ⏳
- ⏳ FRED 7개 시리즈 수집 + CSV 캐시
- ⏳ SEC N-PORT 전처리 → 선택 펀드 parquet
- ⏳ GDELT DOC 2.0 클라이언트 (조회 가능 기간 확인 필요)
- ⏳ `data/SOURCES.md` 작성
- **완료 기준**: 7개 시리즈 CSV, 선택 펀드 parquet

## Phase 2 — 합성 코퍼스 ⏳
- ⏳ `source_notes/` 공개 보고서 요지 정리
- ⏳ `scripts/gen_playbooks.py` → 플레이북 12개 (약 100조항, protected 포함) + 사람 검수
- ⏳ 사건 카드 6개 + calm 구간 3개 (공개 출처 URL 필수)
- ⏳ 가상 포트폴리오 (`portfolio.json`)
- ⏳ 백테스트 정답 라벨 (`labels/*.json`)
- **완료 기준**: 스키마 검증 통과, 전 문서 `synthetic: true`, 출처 URL 기재

## Phase 3 — Sentinel (상시 감시) ⏳
- ⏳ 시그널 A: FRED z-score (252영업일)
- ⏳ 시그널 B: GDELT 기사량 z-score + 출처 수 + 군집화
- ⏳ 이중 트리거 등급 (`ALERT` / `WATCH` / `NONE`), 72h 병합
- ⏳ 백테스트 모드 미래 정보 누수 차단 + 테스트
- **완료 기준**: 6개 사건 ALERT 재현 시도, calm 구간 오경보 측정

## Phase 4 — Matcher (적합도 판단) ⏳
- ⏳ 사건 구조화 (텍스트 → `Event`)
- ⏳ ChromaDB 임베딩 검색 top-30 + protected 조항 항상 포함
- ⏳ 조항별 판정 (배치, 근거 인용 필수, 실패 시 재시도 2회 → `uncertain`)
- ⏳ `fit_score` 계산, 공백(gap) 채널 탐지
- ⏳ 분기: `fit_score < 0.4` 재검색, `low_confidence` 플래그
- **완료 기준**: 6개 사건 MatchResult 생성, 근거 없는 판정 0건

## Phase 5 — Exposure (노출 경고) ⏳
- ⏳ networkx 보유 경로 그래프 구성
- ⏳ 규칙 기반 `relevance` (+ 이름 매칭 실패 시 LLM 보조)
- ⏳ `risk_score` 계산, 상위 10개 경로 + `why` 생성
- **완료 기준**: 사건별 상위 경로와 `why` 생성

## Phase 6 — Orchestrator + Briefing ⏳
- ⏳ Gemini function calling 루프 (`max_steps=10`, 도구 7개)
- ⏳ 하드 제약: `build_briefing` 선행 도구 강제 + 테스트
- ⏳ `traces` 테이블 저장
- ⏳ `Briefing` 생성 (`actions_to_check` 집계)
- **완료 기준**: `run_replay(event_id)`가 Briefing 반환

## Phase 7 — 서비스 계층 + UI + 배포 ⏳
- ⏳ `app/services.py` 9개 함수
- ⏳ Streamlit 5탭 (감시 / 브리핑 / 승인 / 백테스트 / 학습 층)
- ⏳ 합성 데이터 배지 표시
- ⏳ Streamlit Community Cloud 배포 (`st.secrets`, 커밋 데이터로 시작 시 재구성)
- **완료 기준**: 외부 접속 가능한 데모 URL, 재시작 후에도 정상 기동

## Phase 8 — 백테스트 ⏳
- ⏳ `scripts/run_backtest.py` 지표 산출 (lead_time, doc_top3_hit, clause_PR, gap_PR, path_recall, false_alarms)
- ⏳ 임계치·가중치 보정 (`config.yaml`)
- **완료 기준**: `backtest_results.json` 생성 (실제 실행값만 기록)

## Phase 9 — Learner (알파 썬셋) ⏳
- ⏳ 우선순위 점수 엔진 (cite_norm + fb + recency + explore, protected 하한)
- ⏳ `shadow_log` 상시 기록 (모드별 분리 집계)
- ⏳ `set_learner_enabled` 토글 + 변경 이력
- ⏳ ON/OFF 비교 → `learner_delta`
- ⏳ 테스트: OFF 시 순위 = `fit_score`, sandbox 로그 라이브 미유입
- **완료 기준**: `learner_delta` 산출, 라이브 점수에 sandbox 미유입 테스트 통과

## Phase 10 — 제출물 ⏳
- ⏳ README 정식본 (실행법·환경·데이터 출처·합성 명시·라벨 순환 위험 명시)
- ⏳ 발표자료용 결과 요약
- ⏳ `llm_calls` 기반 API 사용 내역 정리

---

## ⏸️ 보류 (MVP 제외 — plans.md 12장)
- ⏸️ 자금 유출입(ETF flow 등) 감시 신호 — 무료·안정적 공개 데이터 미정, 자금시장 지표로 대체
- ⏸️ 피드백·`shadow_log` 영속 저장소 — 데모는 비영속
- ⏸️ 실제 기관 문서·포트폴리오 연동

## 🗑️ 폐기 (채택하지 않기로 한 것)
- 🗑️ FastAPI 서비스 계층 — Streamlit이 서비스 함수 직접 호출로 대체
- 🗑️ 별도 API 서버·Docker — Streamlit Community Cloud 제약
- 🗑️ 모델 로컬 로딩 — 리소스 제한, 전부 API 호출
- 🗑️ 인용 빈도 단독 우선순위 — 편향 문제로 복합 점수(5.4)로 대체
