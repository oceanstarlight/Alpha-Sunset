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

## GDELT DOC 2.0 (라이브 시그널 B)
- URL: https://api.gdeltproject.org/api/v2/doc/doc (`timelinevolraw`, `artlist` 모드)
- 약관: GDELT 무료 공개 데이터, 요청 간격 5초당 1회 제한
- 범위: 최근 약 3개월. 라이브 모드 전용, 데이터 저장 안 함

## 합성 데이터
- `data/playbooks/*.json`: `data/source_notes/` 요지를 근거로 Claude가 초안 작성, 사람 검수 대상. 모두 `synthetic: true`
- `data/portfolio.json`: 가상 기관·가상 운용사·가상 카운터파티. 비중 모두 가상값. 프록시 펀드(KRE, EMB, HYG, XLE, MCHI, VGK, IVV, EWY)는 실존 공개 펀드이며 보유내역은 P1에서 SEC N-PORT로 수집
- `data/labels/*.json`: 사용자가 직접 설계한 합성 라벨
