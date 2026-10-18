# Alpha Sunset

> 위기 사건 ↔ 내부 대응문서 적합도 판단 + 보유 자산 노출 경고 AI Agent
> KIC AI 에이전트 공모전 (주제: 투자·금융 업무 혁신 AI Agent) 본선 MVP

문서를 찾아주는 AI가 아니라, **"이 문서가 이번 사건에 맞는지, 어디가 안 맞고 무엇이 비어 있는지 알려주는 AI"**.
에이전트는 제안만 하고, 최종 결정은 사람이 승인한다. 문서는 삭제·폐기하지 않는다.

**데모**: https://alpha-sunset.streamlit.app

> ⚠️ **합성 데이터 고지**: 대응문서(플레이북)·포트폴리오·백테스트 라벨은 모두 가상으로 재구성한 합성 데이터다 (`synthetic: true`).
> 사건 카드의 사실관계와 시장·자금 흐름·펀드 보유 데이터는 공개 출처에서 수집했다 ([`data/SOURCES.md`](data/SOURCES.md)).
> 플레이북 조항은 실제 기관 매뉴얼·감독 규정·약관을 옮긴 것이 아니라 공개 사건 사실을 근거로 재구성한 기획 단계 합성 데이터다 (사용자 검수: 합성 수용, [`docs/PLAYBOOK_REVIEW.md`](docs/PLAYBOOK_REVIEW.md)).
> **실제 공개 규정·가이드라인 또는 기관 내부 문서 기반 조항으로 확장·교체할 수 있다** (같은 스키마 사용, 교체 시 라벨·지표 재계산).

---

## 1. 문제
- 기관의 위기 대응 문서는 여러 부서·문서에 흩어져 있고, 각 문서는 작성 당시 사건의 전제에 묶여 있다.
  예: 코로나 때 만든 유동성 매뉴얼은 지정학·관세 충격에는 일부 조항만 맞는다.
- 사건이 터졌을 때 "어떤 문서가 지금 맞는가"를 빠르게 판단하기 어렵다.
- 위탁운용사·펀드·거래상대방을 거친 간접 노출은 종목 매핑만으로는 보이지 않는다.

## 2. 동작 방식 (2단계 운영)
| 단계 | 조건 | 에이전트가 하는 일 |
|---|---|---|
| **1단계: 자금 이상 알림** | 시장 신호(A) 또는 자금 흐름 신호(C)가 5영업일 중 2일 이상 이상 | 알림만 띄운다 (사건 확정 전) |
| **2단계: 대응안** | 사건 확정(B) + 1단계 | 문서 적합도 판정, 공백 탐지, 보유 노출 추적, 담당별 확인 항목을 담은 브리핑 생성 |

| 구성 요소 | 내용 |
|---|---|
| **Sentinel** (상시 감시) | A: FRED 시장 지표 1일 변화 z-score / C: FRED 주간 자금 흐름(MMF·예금·해외 공적 미국채·지준, 공표 시차 반영) / B: 라이브 GDELT 기사량 급증·출처 수, 백테스트는 사건 카드. 라이브는 GitHub Actions가 매일 07시(KST) 수집해 커밋하고, GDELT 조회 실패는 '판단 불가'로 구분 표시 |
| **Matcher** (적합도 판단) | 조항 검색(ChromaDB, protected 조항 항상 포함) → 조항별 적용/부분적용/부적용 판정(Gemini). 근거 인용문이 조항 원문·사건 요약의 실제 문구인지 코드로 검증, 실패 시 `uncertain` |
| **Exposure** (노출 경고) | 기관 → 직접·위탁운용사·거래상대방 → 프록시 펀드(SEC N-PORT 보유내역) → 발행자·국가 그래프. 사건 기관과 같은 발행자, 사건 지역과 직접 겹치는 핵심 경로는 별도 표시 |
| **Orchestrator** | Gemini 함수 호출로 도구 순서를 정한다. 도구 입력·상태는 코드가 보유(LLM이 데이터를 조작하지 못함). 판정·노출 분석 전 브리핑 생성은 코드로 거부. 모든 호출은 trace로 저장 |
| **세계 금융 지도** (메인 탭) | 세계 지도 위 원으로 사건 지역(심각도)·국가별 보유 비중·영향도(노출 경로 risk 합)·GDELT 보도 매체 국가를 표시 |
| **Learner** (알파 썬셋) | 인용·피드백 이력으로 문서 검색 우선순위를 보정 (최대 ±15%, protected 하한, 기본 OFF) |

## 3. 백테스트 결과 (실제 실행값)
사건 6개: 2008 리먼, 2020 코로나, 2022 러시아-우크라이나, 2022 레고랜드, 2023 SVB, 2025 미국 관세.
전체 수치는 [`data/backtest_results.json`](data/backtest_results.json).

| 지표 | 값 | 해석 |
|---|---|---|
| 경보 재현 | 6/6 | 사건 확정일 기준 |
| 사건 확정 → 대응안 지연 | 0.33일 | |
| 사건 전 자금 이상 알림 선행일 | 평균 28.6일 (5/6 사건) | ⚠️ 평상일에도 직전 60일 내 알림이 있었던 비율이 42% → 일부는 우연일 수 있음 |
| 평상시 자금 이상 알림 비율 | 9.19% | 알림 피로도 (연 약 23영업일) |
| 꼭 봐야 할 문서 top3 적중 | 0.72 | |
| 노출 경로 재현율 | 0.75 | gfc_2008 제외 (N-PORT 2019년 이전 미공개) |
| 공백 탐지 (핵심 문서 제거 검증) | 정밀도 1.0 / 재현율 0.75 | 라벨이 모두 '공백 없음'이라 문서 제거 실험으로 별도 검증 |
| 부적용 조항 정밀도 / 재현율 | 0.07 / 0.22 | 라벨에 '헷갈리는' 조항 일부만 담아 정밀도가 구조적으로 낮음 |
| 근거 없는 판정 | 0건 | |
| Learner ON − OFF (top3 적중) | 0.0 | 사건 유형별 이력이 없고, 보정 폭(±15%)이 보수적이라 순위 변화 없음 (설계 의도대로 유지) |

## 4. 검증 원칙 (편향 방지)
- **사건일 시점 정보만 사용**: 백테스트 입력은 사건 카드의 `summary_as_of`(사건일 당일까지 알려진 사실)만 쓴다. 보유내역도 사건일 이전에 공시된 것만 쓴다.
- **사전 등록**: 검증 규칙·정답·지표 정의를 실행 전에 커밋으로 고정했다 ([`data/backtest/ablation/preregistration*.json`](data/backtest/ablation/)). 결과를 보고 바꾸려면 새 버전으로 등록한다.
- **라벨 독립성**: 라벨은 에이전트 결과·캐시·코드·사후 요약이 없는 격리 폴더에서 별도 서브에이전트(Claude Sonnet)가 초안을 만들고 사용자가 검수했다. 정책 대응 조항은 보수적으로 판정했다.
- **튜닝 금지**: 임계치·가중치는 사건 6개 성적으로 조정하지 않는다 (과적합 방지).
- **데이터 선택**: 데이터 제외는 품질(커버리지·공백·공표 지연·평상 발동률)로만 판단한다. 기관 MMF(WIMFNS)는 2021년 중단으로 제외했다.

## 5. 한계
- 대응문서·포트폴리오·라벨이 합성이고 사건이 6개뿐이라 지표의 통계적 신뢰도는 낮다.
- 플레이북은 실제 규정 부합 여부(현실성)를 검수하지 않았다. 실제 규정 기반 조항으로 교체하는 확장 경로를 열어 두었다.
- 라벨과 Learner 시뮬레이션 피드백이 같은 출처(라벨)에서 나와 순환 위험이 있다.
- 백테스트의 사건 신호(B)는 사건 카드 날짜에 묶여 있어, 사건 확정 전 경보(ALERT)는 구조적으로 불가능하다. 사건 전에는 1단계 알림만 낸다.
- 위탁운용사 노출은 공개 펀드를 프록시로 추정한다 (불확실성 0.3 반영).
- 한국 일간 자금 흐름(KRX 외국인 순매수)은 인증키 확보 후 추가 예정이다.

## 6. 실행 방법
```bash
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env      # GEMINI_API_KEY, SEC_USER_AGENT
.venv/bin/streamlit run ui/streamlit_app.py
.venv/bin/pytest -q       # 118개 테스트
```
- **API 키 없이도** 백테스트 재생은 동작한다. 커밋된 LLM 응답 캐시(`data/llm_cache.db`)로 같은 결과를 재현한다.
- 배포: Streamlit Community Cloud (`ui/streamlit_app.py`, Python 3.11, Secrets에 `GEMINI_API_KEY`·`SEC_USER_AGENT`).

| 스크립트 | 역할 |
|---|---|
| `scripts/build_holdings.py` | SEC N-PORT 보유내역 수집 |
| `scripts/run_sentinel_backtest.py` | 경보 재생 |
| `scripts/run_matcher.py` · `run_exposure.py` | 적합도 판정 · 노출 분석 |
| `scripts/run_replay.py` | 에이전트 전체 재생 → 브리핑 |
| `scripts/run_ablation.py` | 공백 탐지 검증 (문서 제거) |
| `scripts/run_flow_quality.py` | 자금 흐름 데이터 품질 보고서 |
| `scripts/run_learner_sim.py` | Learner ON/OFF 비교 |
| `scripts/run_backtest.py` | 지표 산출 → `data/backtest_results.json` |
| `scripts/validate_data.py` | 코퍼스·라벨 스키마·참조 검증 |
| `scripts/collect_signals.py` | 일일 라이브 시그널 수집 (GitHub Actions, `data/live/`) |

## 7. 기술 스택과 비용
- Python 3.11 · Streamlit · Pydantic v2 · Gemini API(`gemini-3.5-flash-lite`, `gemini-embedding-001`) · ChromaDB · SQLite · networkx · pandas
- 무료 도구·무료 API 등급만 사용 (Gemini 무료 등급 분당 15회 제한에 맞춰 요청 간격·재시도 내장)
- **API 사용 내역**: 모든 LLM 호출은 단일 래퍼(`app/llm/client.py`)를 거쳐 `llm_calls` 테이블(시각·모델·입출력 토큰·용도·캐시 여부)에 기록된다. 현재 캐시: 생성 187건, 함수 호출 104건, 임베딩 108건.

## 8. 저장소 구조
```
app/
  agents/      sentinel · matcher · exposure · orchestrator · learner
  data/        fred · gdelt · nport 클라이언트
  llm/         단일 LLM 래퍼 + 응답 캐시
  backtest.py  지표 · geo.py(지도 집계) · schemas.py · services.py(UI 진입 함수)
ui/streamlit_app.py   6탭 UI (세계 금융 지도 / 감시 / 브리핑 / 승인 / 백테스트 / 학습 층)
data/          사건 카드 · 플레이북 · 포트폴리오 · 라벨 · FRED · N-PORT · 백테스트 결과
docs/          plans.md(계획·결정 기록) · Current.md(진행 현황)
```
