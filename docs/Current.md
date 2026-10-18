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
| P1 | 외부 데이터 수집 | ✅ 완료 |
| P2 | 합성 코퍼스 | ✅ 완료 |
| P3 | Sentinel (상시 감시) | ✅ 완료 |
| P4 | Matcher (적합도 판단) | ✅ 완료 (라벨 채점 대기) |
| P5 | Exposure (노출 경고) | ✅ 완료 |
| P6 | Orchestrator + Briefing | ✅ 완료 |
| P7 | 서비스 계층 + UI + 배포 | ✅ 완료 |
| P8 | 백테스트 | ✅ 완료 |
| P9 | Learner (알파 썬셋) | ✅ 완료 |
| P10 | 제출물 | 🔄 진행 중 (README 완료) |

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

## P1 — 외부 데이터 수집 ✅
- ✅ FRED 8개 시리즈 수집 + CSV 캐시 (`app/data/fred.py`, BAA10Y 포함)
- ✅ SEC N-PORT: 프록시 펀드 8개 × 스냅샷 6개(사건 5 + live) = 48개 parquet (`app/data/nport.py`, `scripts/build_holdings.py`)
  - 분기 데이터셋(수백 MB) 대신 펀드별 NPORT-P XML만 수집, 사건일 이전 공시만 사용(누수 방지), gfc_2008 제외
- ✅ GDELT DOC 2.0 클라이언트 (`app/data/gdelt.py`, 요청 간격 6초·429 재시도)
- ✅ `data/SOURCES.md` 작성
- **완료 기준**: 시리즈 CSV ✅, 선택 펀드 parquet ✅

## P2 — 합성 코퍼스 ✅
- ✅ `source_notes/` 공개 자료 요지 12개 (확인된 사실만 기록)
- ✅ 플레이북 12개 / 96조항 (protected 10개: regulatory 6, insurance 4) — Claude 초안, `scripts/gen_playbooks.py`로 검증
- ✅ 플레이북 사람 검수: 합성 수용(실제 규정 기반 아님 확인, `docs/PLAYBOOK_REVIEW.md`) → 추후 실제 규정 기반 조항으로 확장·교체 가능
- ✅ 사건 카드 6개 (공개 출처 URL 확인) + calm 구간 3개 (2014Q2, 2017Q4, 2024Q1 — FRED 기준 선정)
- ✅ 가상 포트폴리오 (직접 6, 위탁운용사 6, 카운터파티 5)
- ✅ 백테스트 정답 라벨 — 격리 서브에이전트 초안 + 사용자 검수 (P8)
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

## P4 — Matcher (적합도 판단) ✅
- ✅ 사건 구조화 (`structure_event`) + 백테스트 카드 재추출 검증 (`verify_card`, 카드 값으로 판정)
- ✅ ChromaDB 검색 top-30 + protected 조항 항상 포함 (`app/retrieval.py`, 코퍼스 지문 바뀌면 재색인)
- ✅ 조항별 배치 판정: 근거 인용문이 조항 원문·사건 요약의 실제 문구인지 검증, 실패 조항만 재시도 2회 → `uncertain`
- ✅ `fit_score`, 공백 채널, `fit_score < 0.4` 재검색, `low_confidence`, 순위(Learner OFF = fit_score 순)
- ✅ `scripts/run_matcher.py` → `data/backtest/match/*.json`, `match_summary.json`
- ✅ LLM 래퍼에 무료 등급 분당 요청 제한(14회)·429 대기 재시도 추가, 캐시로 키 없이 재현 확인
- **완료 기준**: 6개 사건 MatchResult 생성 ✅, 근거 없는 판정 0건 ✅
- ⚠️ 6개 사건 모두 공백 채널 0 → partial도 '다룸'으로 보는 규칙이 느슨할 수 있음. 라벨 나오면 P8에서 조정
- ⚠️ 판정 품질(top3 적중, 부적합 조항 P/R)은 라벨이 있어야 채점 가능
- ⚠️ 사건 카드 요약에 사건일 이후 사실(예: 11월 환율 고점)이 포함됨 → 판정 입력 누수 가능, P8에서 사건일 기준 요약 분리 검토

## P5 — Exposure (노출 경고) ✅
- ✅ networkx 그래프: 기관 → 직접/위탁운용사/카운터파티 → 프록시 펀드 → 보유(발행자·국가별 묶음) → 지역·업종
- ✅ 규칙 기반 `relevance` (지역 0.4·업종 0.35·자산군 0.25, 유럽·신흥국 지역 그룹 매핑)
- ✅ 이름 매칭: 규칙(토큰 완전 일치) → 실패한 민간 기관만 LLM 보조, 공공기관(중앙은행·정부·감독기관) 매칭 제외
- ✅ `risk_score = weight × relevance × (1 − 0.5·uncertainty)`, 상위 10개 + `why`(LLM, 경로 속성만 입력)
- ✅ 사건 기관과 같은 발행자 보유는 `entity_paths`로 별도 표시 (예: svb_2023 → KRE의 SVB Financial Group, Signature Bank)
- ✅ 불확실 경로 비율 계산 (`needs_requery`) — 추가 조회 후 재계산은 P6 Orchestrator에서 연결
- ✅ `scripts/run_exposure.py` → `data/backtest/exposure/*.json` (gfc_2008 제외)
- **완료 기준**: 사건별 상위 경로와 `why` 생성 ✅ (5개 사건)
- ⚠️ 순위가 큰 직접 보유(국채·대형주 ETF)에 쏠림: 사건 지역에 GLOBAL이 있으면 모든 노드가 지역 일치로 잡힘. ru_ua_2022에서 EMB의 러시아·우크라이나 국채 경로가 30위·38위 → **P8에서 라벨 기준으로 조정 (사용자 결정)**

## P6 — Orchestrator + Briefing ✅
- ✅ Gemini 함수 호출 루프 (`max_steps=10`, 도구 7개). LLM은 호출 순서만 정하고 도구 입력·상태는 코드가 보유
- ✅ 하드 제약: `build_briefing`은 `judge_clauses`·`compute_exposure` 실행 후에만 허용 + 테스트
- ✅ 분기 규칙: fit_score < 0.4 확장 재검색 1회, 불확실 경로 비율 > 0.5 보유내역 재조회 1회(백테스트는 추가 공시 없음을 기록)
- ✅ LLM이 브리핑까지 못 가면 남은 단계를 코드가 정해진 순서로 실행 (trace에 `fallback` 기록)
- ✅ `traces`·`briefings` 테이블 저장, `get_trace`·`get_briefing`
- ✅ `actions_to_check`: applicable/partial 조항의 조치를 담당 역할별로 모으고 중복 조치는 조항 번호만 합침, LLM은 문장 정리만
- ✅ `scripts/run_replay.py` → `data/backtest/briefings/*.json`, 캐시로 키 없이 재현 확인
- **완료 기준**: `run_replay(event_id)`가 Briefing 반환 ✅ (6개 사건, LLM이 7단계 모두 권장 순서로 호출, fallback 0회)
- ⚠️ 재생 기준일 = 사건 카드 date라 covid_2020·tariff_2025는 WATCH (시장 신호가 다음 날 켜짐, P3 결과와 동일)
- ⚠️ 확인 항목이 사건당 12~35개로 많음 → UI(P7)에서 담당 역할별 묶음 표시 예정

## P7 — 서비스 계층 + UI + 배포 ✅
- ✅ `app/services.py` 9개 함수 + `load_saved_briefing`, `record_approval`
  - `run_live`: FRED 갱신 + GDELT 뉴스 군집 → LLM 구조화 → 라이브 브리핑 (live DB, 최신 보유내역)
  - `submit_feedback`: feedback + shadow_log (브리핑 모드에 맞춰 live/backtest 분리)
  - `set_learner_enabled`: P9 전에는 ON 거부, 모든 시도 기록
- ✅ 브리핑 생성 시 `shadow_log`에 문서별 인용·순위 상시 기록
- ✅ Streamlit 5탭 (`ui/streamlit_app.py`): 감시(경보 재생·FRED 차트·라이브 조회) / 브리핑(적합도·근거·공백·노출 그래프·담당별 확인 항목·출처·trace) / 승인(문서 피드백·승인/반려) / 백테스트 / 학습 층, 합성 데이터 배지
- ✅ 콜드 스타트 확인: 새로 받은 저장소에서 키 없이 `run_replay` 성공 (Chroma·sandbox.db 자동 재구성)
- ✅ AppTest·서비스 테스트 추가
- ✅ Streamlit Community Cloud 배포: https://alpha-sunset.streamlit.app (사용자 확인)
- ✅ 배포 환경 Reboot 후 정상 기동 (사용자 확인)
- ⏳ 라이브 GDELT 호출을 배포 환경에서 재확인 (현재 세션은 429)
- **완료 기준**: 외부 접속 가능한 데모 URL ✅, 재시작 후에도 정상 기동 (콜드 스타트 로컬 검증 ✅, 배포 환경 Reboot ✅)

## P8 — 백테스트 ✅
- ✅ 사건일 시점 요약 분리 (`summary_as_of`·`entities_as_of`, 백테스트 입력은 `as_of_view()`)
- ✅ 지표 엔진 `app/backtest.py` + `scripts/run_backtest.py` → `data/backtest_results.json`
- ✅ 라벨 6개: 격리 폴더의 Sonnet 서브에이전트 초안 + 사용자 검수 (정책 대응 조항은 보수적으로 부적용, covid 대응일은 기계적 규칙으로 교체)
- ✅ 사전 등록 v1·v2 (`data/backtest/ablation/preregistration*.json`): 실행 전에 규칙·정답을 커밋으로 고정
- ✅ 자금 흐름 신호 C (FRED 주간 5종, 공표 시차 반영) + 등급 v2 (ALERT = B ∧ (A ∨ C))
- ✅ 데이터 품질 보고서 `data/backtest/flow_quality.json`: WIMFNS(2021 중단) 제외 권고, 나머지 4종 유지
- ✅ 기계적 대응일(`reaction_date_flow`)과 `lead_time_flow` 지표
- ✅ 공백 규칙 v2 (partial은 전제 사건유형이 일치할 때만 '다룸') → 문서 제거 검증 재현율 0.625 → 0.75, 정밀도 1.0
- ✅ protected 조항만 판정된 문서는 순위 하단(후보 유지)
- ✅ 노출 핵심 경로(`exposure_core`): 사건의 구체 지역과 일치하지만 상위 10 밖인 경로 별도 표시
- ✅ 임계치·가중치는 라벨로 튜닝하지 않음 (과적합 방지, 사전 등록)

### 2단계 운영 지표 (사전 등록 v3, 1차 지표)
| 지표 | 값 | 비고 |
|---|---|---|
| 사건 전 자금 이상 알림 선행일 (평균) | 28.6일 | 5/6 사건 (tariff_2025 없음) |
| 사건 전 60일 내 알림이 있었던 사건 비율 | 83% | **기준선: 평상일 42%** → 일부는 우연일 수 있음 |
| 사건 확정 → 대응안 지연 | 0.33일 | |
| 평상시 자금 이상 알림 비율 (알림 피로도) | 9.19% | 연 약 23영업일 |

### 지표 (실제 실행값, 라벨 6개)
| 지표 | 값 | 비고 |
|---|---|---|
| doc_top3_hit | 0.72 | |
| clause precision / recall | 0.07 / 0.22 | 라벨은 '헷갈리는' 조항 일부만 담아 precision이 구조적으로 낮음 |
| gap P/R (라벨) | 1.0 / 1.0 | 라벨이 모두 '공백 없음'이라 변별력 없음 → 문서 제거 검증 사용 |
| gap P/R (문서 제거 검증, v2) | 1.0 / 0.75 | |
| path_recall | 0.75 | gfc_2008 제외 |
| lead_time (라벨 대응일) | −6.3일 | covid −41일 |
| lead_time_flow (기계적 대응일) | −24.2일 | 자금·시장 이상 신호보다 경보가 평균 24일 늦음 |
| 무작위 평상 구간 발동률 A / C | 4.13% / 5.19% | |
| 경보 재현 | 6/6 | calm ALERT 0 |

### 남은 결정·작업
- 🔁 KRX 외국인 순매수 → ECOS로 대체 (KRX Open API는 약관 문제로 제외)
- ✅ WIMFNS 제외 (사용자 결정, 사전 등록 v3)
- ✅ 조기 사건 카드는 추가하지 않음 (사용자 결정: 특정 사건 맞춤 데이터 금지) → 2단계 운영(자금 이상 알림 → 사건 확정 시 대응안)으로 평가 체계 전환

## P9 — Learner (알파 썬셋) ✅
- ✅ 점수 엔진 `app/agents/learner.py` (plans.md 5.4 그대로, 사전 등록 v4): cite_norm·fb·recency·explore, protected 하한 0.5
- ✅ `shadow_log` 상시 기록, 모드별 분리 집계 (live는 live.db, backtest·sim은 sandbox.db)
- ✅ 토글: UI·`set_learner_enabled`, 변경 이력 `learner_toggle_log`, ON이면 Orchestrator `get_priority`에서 순위 보정
- ✅ ON/OFF 비교 `scripts/run_learner_sim.py` → `data/backtest/learner_results.json`
- ✅ 테스트: OFF 시 순위 = fit_score, 라이브 점수에 sandbox 로그 미유입, 공식 검증, protected 하한
- **완료 기준**: `learner_delta` 산출 ✅, sandbox 미유입 테스트 ✅
- ⚠️ 결과: learner_delta = 0.0 (실제 순서 1회), learner_delta_sim = 0.0 (같은 사건 2회 반복)
  - 1회 재생: 사건 유형이 모두 달라 유형별 이력이 없음 → 구조적으로 효과 없음
  - 반복 재생: Learner가 놓친 정답 문서의 priority를 올렸지만(예: svb PB-RATE 0.81), 보정 폭이 최대 ±15%(boost 0.3)라 fit 차이를 못 넘음. ru_ua PB-REG는 protected 조항만 판정된 문서라 하단 규칙에 걸림
  - 사전 등록대로 가중치는 조정하지 않음 → **사용자 결정: 보수적 설계(A안) 유지, 효과 0을 그대로 보고**

## P10 — 제출물 🔄
- ✅ README 정식본 (문제·2단계 운영·구성·실제 백테스트 결과·검증 원칙·한계·실행법·API 사용 내역·합성 고지)
- ⏳ 발표자료용 결과 요약
- ✅ `llm_calls` 기반 API 사용 내역 정리 (`docs/API_USAGE.md`)

## 추가 — 세계 금융 지도 · 라이브 GDELT 안정화 ✅
- ✅ 메인 탭 "세계 금융 지도" (`app/geo.py` + pydeck): 사건 지역(빨강)·보유 비중(파랑)·영향도(주황)·GDELT 보도 국가(보라) 원 표시, 레이어 선택·툴팁·상위 국가 표
- ✅ GDELT 클라이언트: 요청 간격 10초, 429·연결 끊김 점증 대기 재시도(최대 4회), 기사 `sourcecountry` 수집
- ✅ 사건 신호 상태 `ok / partial / unavailable`: 전부 실패하면 '사건 없음'이 아니라 '판단 불가'로 표시, 실패 원인 펼쳐 보기
- ✅ GitHub Actions 일일 수집기 (`scripts/collect_signals.py`, 매일 07:07 KST) → `data/live/` 커밋, UI는 수집 결과 기본 + 직접 조회 보조
- ⚠️ GDELT GEO 2.0 API는 404 → 지도의 GDELT 원은 사건 위치가 아니라 **보도 매체 국가**

## 추가 — 한국(로컬) 시장 상시 감시 🔄
- ✅ 사전 등록 v5 확정 `data/backtest/ablation/preregistration_v5_kr.json` (사용자 결정 반영)
  - 로컬 대응안에 해외 사건 포함 + 해외-한국 연관성 근거(동시 반응·과거 상관·노출 경로) 필수 첨부
  - 한국 뉴스 최소 언론사 10곳 / DART 신용 공시 단독은 경고만, 뉴스 교차 확인 + 로컬 1단계일 때 대응안
  - A_kr: ECOS 코스피·원달러·국고채3년·회사채AA−국고채 스프레드·CD91 / C_kr: 외국인 순매수 / B_kr: Google 뉴스 RSS + DART 신용 공시
  - 공식 무료 소스만 (사용자 결정), 임계치는 글로벌과 동일, 알림은 텔레그램
- ✅ 모든 경보 판단에 원인→근거→결과 표 (`sentinel.explain`): 감시 탭 라이브·백테스트(첫 알림일·첫 ALERT일)
- ✅ UI 시장 선택: 로컬(대한민국, 기본) / 글로벌 — 수집은 항상 둘 다, 표시 범위만 변경
- ✅ 로컬 감시 뼈대
  - 데이터 클라이언트 `app/data/korea.py`: DART·Google RSS·ECOS
  - 로컬 Sentinel `app/agents/local.py`: A_kr·C_kr·B_kr, DART 경고·확정, 연관성 근거, 원인-근거-결과
  - 알림·리포트: `app/notify.py`(텔레그램, 24시간 중복 방지), `app/report.py`(대응안 리포트)
  - 실행: `scripts/monitor_kr.py`, `.github/workflows/monitor_kr.yml`(평일 30분마다 + 하루 2회 daily)
  - 감시 탭(로컬)에 결과·경고·리포트 표시
  - 실제 확인: DART 연결됨 (삼부토건 영업정지 정정 공시 → 사건 경고), Google 뉴스 RSS 연결됨
- 🗑️ KRX Open API 제외 (약관: 비상업적 목적만, 대가 청구 금지 — 사용자 결정)
- 🗑️ 네이버 검색 API 제외 (유료 전환 — 사용자 결정)
- ✅ 키: DART·ECOS·텔레그램 (세션 + GitHub Secrets), 텔레그램 실제 발송 확인 / GitHub Secrets 등록 필요
- ✅ ECOS 항목 코드 검증 완료 (check-ecos 워크플로, 6개 모두 일치: 코스피·외국인 순매수(유가증권)·원/달러·국고채 3년·회사채 AA- 3년·CD 91일)
- ✅ 한국 신호 백테스트 `scripts/run_backtest_kr.py` → `data/backtest/kr_results.json` (ECOS 이력: fetch-ecos 워크플로 → `data/ecos/`)
  - 사건 전 알림 선행 19.8일 (5/6 사건, 기준선 50.7%), 대응안 지연 0.8일 (5/6 재현), 평상시 알림 7.57% (글로벌 9.19%)
  - 레고랜드: 회사채AA−국고채 스프레드 z=+6.2로 대응안 / SVB: 한국 시장 반응 없어 로컬 경보 없음
  - ⚠️ 연관성 근거의 같은 날 상관이 0 근처 (ru_ua): 미국·한국 장 시간 차이로 같은 날짜끼리는 안 맞음 → 시차 1일 정렬(v5.1) 사용자 결정 대기
- ✅ 파이프라인 그림 `docs/pipeline.png`
- ⚠️ 뉴스 기준선은 30분 간격 관측이 같은 시간대 20개 쌓여야 판단 (약 3~4주), 그전엔 '판단 불가'로 표시

---

## ⏸️ 보류 (MVP 제외 — plans.md 12장)
- ✅ ~~자금 유출입 감시 신호~~ → P8에서 FRED 주간 자금 흐름(시그널 C)으로 구현 (한국 일간 데이터만 인증키 대기)
- ⏸️ 피드백·`shadow_log` 영속 저장소 — 데모는 비영속
- ⏸️ 실제 기관 문서·포트폴리오 연동

## 🗑️ 폐기 (채택하지 않기로 한 것)
- 🗑️ FastAPI 서비스 계층 — Streamlit이 서비스 함수 직접 호출로 대체
- 🗑️ 별도 API 서버·Docker — Streamlit Community Cloud 제약
- 🗑️ 모델 로컬 로딩 — 리소스 제한, 전부 API 호출
- 🗑️ 인용 빈도 단독 우선순위 — 편향 문제로 복합 점수(5.4)로 대체
