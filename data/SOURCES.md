# 외부 데이터 출처

> 이름 · URL · 수집일 · 라이선스/약관 · 전처리. 제출 필수 항목.

## 사건 카드 (`data/events/`)
사건별 `sources` 필드에 URL을 기재했다. 수집일: 2026-10-17. 공개 정부·중앙은행·기관 웹페이지와 언론 보도이며, 사실 요약만 기록하고 원문은 복제하지 않았다.

| 출처 | URL | 용도 |
|---|---|---|
| SEC EDGAR (Lehman 8-K) | https://www.sec.gov/Archives/edgar/data/0000806085/000110465908059632/a08-22764_48k.htm | gfc_2008 |
| Federal Reserve 보도자료 | federalreserve.gov (2008-10-29, 2020-03-19, 2023-03-12) | gfc_2008, covid_2020, svb_2023 |
| WHO 사무총장 발언 (2020-03-11) | who.int | covid_2020 |
| 금융위원회 (영문 보도자료) | https://fsc.go.kr/eng/pr010101/22322 | covid_2020 |
| 영국 정부 공동성명 (2022-02-26) | gov.uk | ru_ua_2022 |
| 미 재무부 보도자료 jy0612 | https://home.treasury.gov/news/press-releases/jy0612 | ru_ua_2022 |
| Asia Pacific Foundation of Canada | asiapacific.ca | legoland_2022 |
| 한국경제·아시아경제 보도 | hankyung.com, asiae.co.kr | legoland_2022 |
| 정책브리핑 (금융위 2022-10-28) | korea.kr | legoland_2022 |
| NBC Bay Area (FDIC 발표 보도) | nbcbayarea.com | svb_2023 |
| White House Fact Sheet (2025-04-02) | whitehouse.gov | tariff_2025 |
| SEC 보도자료 2022-70 (Archegos) | https://www.sec.gov/news/press-release/2022-70 | source_notes |
| 경향신문 (옵티머스 제재 보도) | khan.co.kr | source_notes |

## FRED (시그널 A, 사건 요약 수치, calm 구간 선정)
- URL: https://fred.stlouisfed.org/series/{VIXCLS, T10Y2Y, DGS10, DEXKOUS, DCOILWTICO, DTWEXBGS, BAMLH0A0HYM2, BAA10Y}
- 캐시: `data/fred/*.csv` (`app/data/fred.py`)
- 수집일: 2026-10-17, `fredgraph.csv` 다운로드 (API 키 불필요)
- 약관: FRED 이용약관. 일부 시리즈는 원 제공자 저작권 적용 (예: VIX는 Cboe)
- 전처리: calm 구간 선정 시 1일 변화의 252영업일 z-score 계산 (`data/events/calm_*.json`의 `selection_method`)
- 주의: `BAMLH0A0HYM2`(ICE BofA HY 스프레드)는 FRED 공개 범위가 최근 3년뿐이라 과거 구간은 `BAA10Y`(Moody's Baa 회사채−10년 국채)로 대체

## FRED 자금 흐름 (시그널 C)
- 시리즈: `WRMFNS`(리테일 MMF), `WIMFNS`(기관 MMF, 2021 중단), `DPSACBW027SBOG`(미국 상업은행 예금, H.8), `WMTSECL1`(해외 공적기관 미국채 보관액, H.4.1), `WRESBAL`(지급준비금, H.4.1)
- 수집일: 2026-10-18, `fredgraph.csv` (키 불필요). 공표 시차는 사전 등록 v2에 고정 (45/45/10/3/3일)
- 품질 보고서: `data/backtest/flow_quality.json`

## GDELT DOC 2.0 (사용 중단)
- 공유 IP 요청 제한(429)이 반복돼 라이브에서 제거 (사용자 결정, 2026-10-18). 아래는 이전 기록

## Google 뉴스 RSS (라이브 시그널 B, 글로벌)
- https://news.google.com/rss/search (hl=en-US, gl=US), 키 불필요. 주제별 기사 수·언론사명·상위 제목만 저장 (`data/live/global_news_history.jsonl`, `signals_latest.json`)

## (이전) GDELT DOC 2.0
- URL: https://api.gdeltproject.org/api/v2/doc/doc (`timelinevolraw`, `artlist` 모드)
- 약관: GDELT 무료 공개 데이터, 요청 간격 5초당 1회 제한 (클라이언트는 10초 간격 + 429·연결 끊김 재시도)
- 범위: 최근 약 3개월. 라이브 모드 전용, 데이터 저장 안 함

## SEC EDGAR N-PORT (프록시 펀드 보유내역)
- 티커 → 시리즈 ID: https://www.sec.gov/files/company_tickers_mf.json
- 공시 목록: EDGAR browse-edgar (type=NPORT-P), 본문: 각 공시의 `primary_doc.xml`
- 수집일: 2026-10-18. User-Agent에 연락처 포함(SEC 정책), 초당 10회 이하
- 약관: SEC 공개 데이터 (미국 정부 저작물)
- 전처리: 종목명·LEI·CUSIP·ISIN·평가액(USD)·비중·자산/발행자 분류·국가만 추출해 `data/holdings/{ticker}_{snapshot}.parquet` 저장. 공시별 URL·보고기준일·공시일은 `data/holdings/manifest.json`
- 스냅샷: 사건일 이전에 공개된 가장 최근 공시 + live(최신). gfc_2008은 데이터 없음(2019년 이전 미공개)

## 합성 데이터
- `data/playbooks/*.json`: `data/source_notes/` 요지를 근거로 Claude가 초안 작성, 사람 검수 대상. 모두 `synthetic: true`
- `data/portfolio.json`: 가상 기관·가상 운용사·가상 카운터파티. 비중 모두 가상값. 프록시 펀드(KRE, EMB, HYG, XLE, MCHI, VGK, IVV, EWY)는 실존 공개 펀드이며 보유내역은 SEC N-PORT로 수집(위 항목)
- `data/labels/*.json`: 사용자가 직접 설계한 합성 라벨

## 국가 중심 좌표 (세계 금융 지도)
- 출처: Google Developers Public Data — Canonical countries (https://developers.google.com/public-data/docs/canonical/countries_csv)
- 수집일: 2026-10-18. 약관: CC BY 4.0 (Google Developers 사이트 콘텐츠 라이선스)
- 전처리: 국가코드(ISO 3166-1 alpha-2)·위도·경도·영문명 244행을 `data/geo/country_centroids.csv`로 저장

## 일일 시그널 수집 (`data/live/`)
- `scripts/collect_signals.py`를 GitHub Actions(`.github/workflows/collect_signals.yml`)가 3시간마다 실행해 커밋. GDELT는 주제별 결과를 `gdelt_topics.json`에 쌓는다
- `signals_latest.json`: FRED 시장·자금 흐름 z-score, GDELT 주제별 기사량 신호와 조회 상태, 최근 1일 위기 주제 기사의 보도 매체 국가(`sourcecountry`) 분포. 기사 본문·URL은 저장하지 않고 주제별 상위 제목 3개만 저장
- `signals_history.jsonl`: 일별 요약 1줄씩 누적
- FRED는 임시 폴더에 내려받아 커밋된 `data/fred/` 캐시(백테스트 재현용)를 바꾸지 않는다

## 로컬(대한민국) 감시 — 사전 등록 v5 (공식 무료 소스만)
- OpenDART 공시 목록 API (https://opendart.fss.or.kr/api/list.json): 주요사항보고서(부도·회생·영업정지 등). 무료 키, 일 20,000회. 공시 원문 링크만 저장
- 네이버 검색 API: 사용하지 않음 — 유료 전환 (사용자 확인, 2026-10-18)
- Google 뉴스 RSS (https://news.google.com/rss/search, hl=ko): 키 불필요. 기사 수·언론사명·상위 제목만 저장
- 한국은행 ECOS Open API (https://ecos.bok.or.kr/api): 코스피(802Y001/0001000)·외국인 순매수 유가증권(802Y001/0030000)·원/달러(731Y001/0000001)·국고채 3년(817Y002/010200000)·회사채 AA- 3년(817Y002/010300000)·CD 91일(817Y002/010502000) 일별. 이력은 `data/ecos/`에 저장 (fetch-ecos 워크플로, 2026-10-18 수집)
- KRX Open API: 사용하지 않음 — 약관상 비상업적 목적만 이용 가능하고 결과에 대한 대가 청구 금지 (사용자 결정, 2026-10-18)
- 비공식 시세(Yahoo 등)는 사용자 결정으로 사용하지 않는다

## 엑셀 입력 검증용 파일 (`data/ingest/samples/`)
- `nps_domestic_equity_2025.csv`: 국민연금공단_국내주식 종목별 투자 현황(2025년 말), 공공데이터포털 https://www.data.go.kr/data/3070507/fileData.do (이용허락범위 제한 없음, 무료). 수집일 2026-10-18, 원본 그대로(CP949)
- iShares Core S&P 500 ETF 보유내역 CSV (https://www.ishares.com/us/products/239726/x/latest-holdings.csv): 검증에만 사용, BlackRock 웹사이트 약관상 저장소에 커밋하지 않음 (`scripts/verify_ingest.py --ishares 경로`)
- `broker_balance.xlsx`·`manager_report.xlsx`·`dataguide_style.xlsx`·`unusual_headers.xlsx`·`truth.json`: 같은 합성 보유내역 240종목을 서로 다른 실무 양식으로 쓴 합성 파일과 정답 (`scripts/make_ingest_samples.py`, 실제 기관·단말 데이터 아님)
