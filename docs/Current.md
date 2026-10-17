# Current — 진행 현황

> 기준 문서: [`plans.md`](./plans.md) · P 번호 = plans.md 9장 마일스톤 번호(M0~M10)
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
| P | 내용 | 상태 |
|---|---|---|
| P0 | 스캐폴딩 | ✅ 완료 |
| P1 | 외부 데이터 수집 | 🔄 진행 중 (FRED·GDELT 완료) |
| P2 | 합성 코퍼스 | 🔄 진행 중 (라벨·검수 대기) |
| P3 | Sentinel (상시 감시) | ✅ 완료 |
| P4 | Matcher (적합도 판단) | ⏳ 예정 |
| P5 | Exposure (노출 경고) | ⏳ 예정 |
| P6 | Orchestrator + Briefing | ⏳ 예정 |
| P7 | 서비스 계층 + UI + 배포 | ⏳ 예정 |
| P8 | 백테스트 | ⏳ 예정 |
| P9 | Learner (알파 썬셋) | ⏳ 예정 |
| P10 | 제출물 | ⏳ 예정 |

---

## P0 — 스캐폴딩 ✅
- ✅ 디렉터리 구조 생성 (plans.md 2장, 저장소 루트 기준)
- ✅ `config.yaml`, `.env.example`, `requirements.txt`(버전 고정), `.streamlit/config.toml`
- ✅ `app/schemas.py` — Enum·모델 전체 (plans.md 3장)
- ✅ `app/config.py` — env → `st.secrets` 순 조회
- ✅ `app/db.py` — `live.db` / `sandbox.db` 분리
- ✅ `app/llm/client.py` 단일 래퍼 + `llm/cache.py` + `llm_calls` 로깅
- ✅ 테스트: 스키마 round-trip, 근거 없는 verdict 거부, live/sandbox 분리, LLM 로깅·캐시·재시도
- **완료 기준**: `pytest` 통과 (23 passed), LLM 호출이 `llm_calls`에 기록됨 (fake SDK로 검증, 실제 API 호출은 키 설정 후 확인)

## P1 — 외부 데이터 수집 🔄
- ✅ FRED 8개 시리즈 수집 + CSV 캐시 (`app/data/fred.py`, P3에서 선행 구현, BAA10Y 추가)
- ⏳ SEC N-PORT 전처리 → 선택 펀드 parquet (gfc_2008 제외)
- ✅ GDELT DOC 2.0 클라이언트 (`app/data/gdelt.py`, 요청 간격 6초·429 재시도)
- 🔄 `data/SOURCES.md` 작성 (FRED·GDELT·사건 출처 기록, N-PORT 남음)
- **완료 기준**: 7개 시리즈 CSV, 선택 펀드 parquet

## P2 — 합성 코퍼스 🔄
- ✅ `source_notes/` 공개 자료 요지 12개 (확인된 사실만 기록)
- ✅ 플레이북 12개 / 96조항 (protected 10개: regulatory 6, insurance 4) — Claude 초안, `scripts/gen_playbooks.py`로 검증
- ⏳ 플레이북 사람 검수
- ✅ 사건 카드 6개 (공개 출처 URL 확인) + calm 구간 3개 (2014Q2, 2017Q4, 2024Q1 — FRED 기준 선정)
- ✅ 가상 포트폴리오 (직접 6, 위탁운용사 6, 카운터파티 5)
- ⏳ 백테스트 정답 라벨 — **사용자 직접 설계** (`data/labels/README.md`, `_template.json`)
- ✅ `app/corpus.py` 로더, `scripts/validate_data.py` 전체 검증, 테스트
- **완료 기준**: 스키마 검증 통과, 전 문서 `synthetic: true`, 출처 URL 기재 → 라벨·검수 남음

### P2에서 발견한 P1 이슈
- ⚠️ FRED `BAMLH0A0HYM2`(HY 스프레드)는 공개 범위가 최근 3년뿐 → 과거 백테스트용 대체 시리즈 필요
- ⚠️ SEC N-PORT 공개 데이터는 2019년 이후 → `gfc_2008` 보유내역 스냅샷 확보 불가

## P3 — Sentinel (상시 감시) ✅
- ✅ 시그널 A: FRED z-score (252영업일, 당일 제외), 신용스프레드 HY OAS→BAA10Y 대체
- ✅ 시그널 B: 라이브 GDELT 기사량 z-score + 출처 수 + 제목 군집화 / 백테스트 사건 카드
- ✅ 이중 트리거 등급 (`ALERT` / `WATCH` / `NONE`), 72h 병합
- ✅ 백테스트 미래 정보 누수 차단 (`AsOfPanel`) + 테스트
- ✅ 재생 스크립트 `scripts/run_sentinel_backtest.py` → `data/backtest/sentinel_results.json`
- **완료 기준**: 6개 사건 모두 ALERT 재현 ✅, calm 3구간 ALERT 0·WATCH 0
- ⚠️ calm 구간은 같은 시그널 A 규칙으로 골랐기 때문에 오경보 0은 순환적 결과. P8에서 무작위 평상 구간 추가 측정 필요
- ⚠️ 백테스트 B는 카드 date부터 켜지므로 사건일보다 앞선 ALERT는 구조적으로 불가 (사전 경고는 WATCH 일수로 기록)
- ⚠️ GDELT 실제 호출이 현재 환경에서 429(요청 제한)로 실패 → 응답 형식은 앞선 정상 응답으로 확인, 라이브 검증은 P7 배포 환경에서 재확인

## P4 — Matcher (적합도 판단) ⏳
- ⏳ 사건 구조화 (텍스트 → `Event`)
- ⏳ ChromaDB 임베딩 검색 top-30 + protected 조항 항상 포함
- ⏳ 조항별 판정 (배치, 근거 인용 필수, 실패 시 재시도 2회 → `uncertain`)
- ⏳ `fit_score` 계산, 공백(gap) 채널 탐지
- ⏳ 분기: `fit_score < 0.4` 재검색, `low_confidence` 플래그
- **완료 기준**: 6개 사건 MatchResult 생성, 근거 없는 판정 0건

## P5 — Exposure (노출 경고) ⏳
- ⏳ networkx 보유 경로 그래프 구성
- ⏳ 규칙 기반 `relevance` (+ 이름 매칭 실패 시 LLM 보조)
- ⏳ `risk_score` 계산, 상위 10개 경로 + `why` 생성
- **완료 기준**: 사건별 상위 경로와 `why` 생성

## P6 — Orchestrator + Briefing ⏳
- ⏳ Gemini function calling 루프 (`max_steps=10`, 도구 7개)
- ⏳ 하드 제약: `build_briefing` 선행 도구 강제 + 테스트
- ⏳ `traces` 테이블 저장
- ⏳ `Briefing` 생성 (`actions_to_check` 집계)
- **완료 기준**: `run_replay(event_id)`가 Briefing 반환

## P7 — 서비스 계층 + UI + 배포 ⏳
- ⏳ `app/services.py` 9개 함수
- ⏳ Streamlit 5탭 (감시 / 브리핑 / 승인 / 백테스트 / 학습 층)
- ⏳ 합성 데이터 배지 표시
- ⏳ Streamlit Community Cloud 배포 (`st.secrets`, 커밋 데이터로 시작 시 재구성)
- **완료 기준**: 외부 접속 가능한 데모 URL, 재시작 후에도 정상 기동

## P8 — 백테스트 ⏳
- ⏳ `scripts/run_backtest.py` 지표 산출 (lead_time, doc_top3_hit, clause_PR, gap_PR, path_recall, false_alarms)
- ⏳ 임계치·가중치 보정 (`config.yaml`)
- **완료 기준**: `backtest_results.json` 생성 (실제 실행값만 기록)

## P9 — Learner (알파 썬셋) ⏳
- ⏳ 우선순위 점수 엔진 (cite_norm + fb + recency + explore, protected 하한)
- ⏳ `shadow_log` 상시 기록 (모드별 분리 집계)
- ⏳ `set_learner_enabled` 토글 + 변경 이력
- ⏳ ON/OFF 비교 → `learner_delta`
- ⏳ 테스트: OFF 시 순위 = `fit_score`, sandbox 로그 라이브 미유입
- **완료 기준**: `learner_delta` 산출, 라이브 점수에 sandbox 미유입 테스트 통과

## P10 — 제출물 ⏳
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
