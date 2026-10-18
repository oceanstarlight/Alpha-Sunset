# 플레이북 검수 시트

> 합성 대응문서 12개·96조항 (Claude 초안). 실무자 관점에서 현실성·일관성을 검수한다.
> **에이전트 판정 결과(`data/backtest/`, 데모 브리핑 탭)는 보지 말고 검수한다.** 결과를 좋게 만들려고 고치면 그것도 편향이다.

## 검수 기준 (조항마다)
1. **현실성**: 실제 기관투자자 위기 대응 매뉴얼에 있을 법한 조항인가
2. **전제 정확성**: 전제(사건유형·채널·지역·조건)가 조항 내용과 맞는가. 너무 넓거나 좁지 않은가
3. **조치 구체성**: 조치가 실행 가능한 수준으로 구체적인가
4. **담당 적절성**: 담당 부서가 맞는가
5. **protected(🔒)**: 규제 필수·보험형이 맞는가

## 작성 방법
- '검수' 칸에 OK / 수정 / 삭제, '의견' 칸에 수정 내용을 적는다. 또는 채팅으로 `PB-LIQ-03: 조치를 ○○로` 처럼 알려줘도 된다.
- 의도된 설계: 문서는 원 사건 전제에 묶여 있어 다른 사건엔 일부만 맞아야 하고, 일부러 오래된 문서(PB-FX·PB-CPTY 2009년)와 중복 조항(현금성 자산 보충 등)을 넣었다.
- 조항 ID는 라벨이 참조하므로 **삭제·ID 변경 시 알려줘야 한다** (라벨 정리 필요).
- 수정 반영 후에는 판정·노출·브리핑·지표를 전부 다시 계산한다 (Gemini 재호출).

자동 점검 표시 조항: 10개 (참고용, 문제라는 뜻은 아님)

## 검수 결과 (2026-10-18, 사용자)
- **전 조항 OK (합성 수용)**: 조항 문구·전제·조치·담당은 실제 기관 매뉴얼·감독 규정·약관을 인용한 것이 아니라, 공개 사건 사실(`data/source_notes/`)을 근거로 Claude가 재구성한 합성 데이터임을 확인하고 기획 단계 데이터로 수용했다.
- 현실성(실제 규정 부합) 검수는 하지 않았다.
- **향후 확장**: 실제 공개 규정·가이드라인 기반 조항으로 확장하거나 교체할 수 있다. 교체 시 라벨 재작성과 판정·노출·지표 전체 재계산이 필요하다 (스키마·파이프라인은 그대로 사용 가능).

## PB-BANK · 은행 시스템 위기 대응 지침
v1.0 · 2023년 · 원 사건 `svb_2023` · 근거 data/source_notes/banking_svb2023.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-BANK-01` | 예치 은행의 폐쇄 또는 뱅크런 징후가 확인되면 해당 은행 예금·결제계좌 잔액을 즉시 확인한다. | banking_stress / counterparty, liquidity / US / 예치 은행 폐쇄·뱅크런 | 은행별 예금 잔액 확인; 부보 한도 초과분 산출 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-BANK-02` | 단일 은행 예치 한도를 초과한 예금은 신용등급이 높은 복수 은행으로 분산한다. | banking_stress / counterparty / - / 단일 은행 예치 집중 | 예치 한도 점검; 복수 은행 분산 이체 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-BANK-03` | 보유 채권의 미실현 평가손실이 큰 지역은행을 식별하고 해당 은행 주식·채권 노출을 점검한다. | banking_stress, rate_shock / rates, counterparty / US / 금리 상승으로 은행 보유채권 평가손실 확대 | 취약 지역은행 식별; 노출 점검 | 신용분석팀 |  | OK | 합성 수용 |
| `PB-BANK-04` | 정부의 예금 전액 보호 또는 긴급 대출 프로그램 발표 시 시장 안정 여부를 확인하고 추가 매도를 보류한다. | banking_stress / liquidity / US / 정부 예금보호·긴급대출 발표 | 정책 효과 모니터링; 추가 매도 보류 판단 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-BANK-05` | 은행 섹터 주가 변동성이 급등하면 은행 섹터 비중을 벤치마크 대비 중립 이하로 조정한다. | banking_stress / equity_vol / US, EU / 은행 섹터 변동성 급등 | 은행 섹터 비중 조정 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-BANK-06` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | banking_stress, liquidity_crisis / liquidity / - / 현금성 자산 비중 하한 미달 | 현금성 자산 비중 점검; 단기 국채·MMF 매수 | 자금운용팀 | ⚠️ 다른 조항과 문구 중복(의도된 중복인지 확인) | OK | 합성 수용 |
| `PB-BANK-07` | 벤처·기술 기업 예금 비중이 높은 은행과 거래하는 위탁운용사에 결제계좌 현황을 확인 요청한다. | banking_stress / counterparty, operational / US / 특정 업종 예금 집중 은행 부실 | 위탁운용사 결제계좌 현황 확인 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-BANK-08` | 은행 위기가 해외 은행으로 전이되는지 확인하기 위해 주요 은행 CDS와 단기자금 금리를 일일 모니터링한다. | banking_stress / credit_spread, liquidity / GLOBAL, EU / 은행 위기 전이 가능성 | 주요 은행 CDS 모니터링; 단기자금 금리 모니터링 | 리스크관리팀 |  | OK | 합성 수용 |

## PB-BCP · 팬데믹 업무연속성계획(BCP)
v1.0 · 2020년 · 원 사건 `covid_2020` · 근거 data/source_notes/pandemic_bcp2020.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-BCP-01` | 감염병 확산으로 사무실 출입이 제한되면 핵심 운용 인력의 분산·재택근무 체계를 가동한다. | pandemic / operational / - / 감염병 확산; 사무실 출입 제한 | 분산·재택근무 가동 | 경영지원팀 |  | OK | 합성 수용 |
| `PB-BCP-02` | 원격 접속 환경에서도 매매·결제 시스템이 정상 작동하는지 일일 점검한다. | pandemic / operational / - / 원격 근무 전환 | 매매·결제 시스템 일일 점검 | IT팀 |  | OK | 합성 수용 |
| `PB-BCP-03` | 핵심 업무별 대체 인력을 지정하고 결재 권한 위임표를 갱신한다. | pandemic, other / operational / - / 핵심 인력 결원 가능성 | 대체 인력 지정; 결재 위임표 갱신 | 경영지원팀 |  | OK | 합성 수용 |
| `PB-BCP-04` | 위탁운용사와 수탁기관의 업무연속성 계획 가동 여부를 확인한다. | pandemic / operational, counterparty / - / 외부 기관 업무 차질 가능성 | 위탁운용사·수탁기관 BCP 확인 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-BCP-05` | 해외 사무소 소재국의 이동 제한 조치를 모니터링하고 출장을 중단한다. | pandemic / operational / GLOBAL / 해외 이동 제한 | 출장 중단; 해외 사무소 근무 체계 점검 | 경영지원팀 |  | OK | 합성 수용 |
| `PB-BCP-06` | 원격 근무 중 정보보안 사고를 막기 위해 접속 기록을 점검한다. | pandemic / operational / - / 원격 근무 장기화 | 접속 기록 점검; 보안 교육 | IT팀 |  | OK | 합성 수용 |
| `PB-BCP-07` | 임직원 확진 시 접촉자 분리와 사무실 방역 절차를 시행한다. | pandemic / operational / - / 임직원 확진 | 접촉자 분리; 방역 시행 | 경영지원팀 |  | OK | 합성 수용 |
| `PB-BCP-08` | 투자위원회는 화상회의로 개최하고 의결 기록을 전자 보관한다. | pandemic / operational / - / 대면 회의 불가 | 화상 투자위원회 운영; 의결 기록 전자 보관 | 경영지원팀 |  | OK | 합성 수용 |

## PB-CMDTY · 원자재 가격 충격 대응 지침
v1.0 · 2022년 · 원 사건 `ru_ua_2022` · 근거 data/source_notes/commodity_2020_2022.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-CMDTY-01` | 유가가 단기간 급등하거나 급락하면 에너지 업종과 원자재 관련 자산의 노출을 집계한다. | geopolitical, supply_chain, pandemic / commodity / GLOBAL / 유가 급변 | 에너지·원자재 노출 집계 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-CMDTY-02` | 선물 만기 직전 극단적 가격 왜곡이 나타나면 원자재 선물·ETF의 롤오버 일정을 점검한다. | pandemic, supply_chain / commodity, liquidity / US / 선물 만기 가격 왜곡; 저장 공간 부족 | 롤오버 일정 점검 | 운용전략팀 | ⚠️ 원 사건 유형(geopolitical)이 전제에 없음 | OK | 합성 수용 |
| `PB-CMDTY-03` | 유가 급락으로 에너지 기업의 하이일드 채권 부도 위험이 커지면 해당 노출을 줄인다. | pandemic, credit_event / commodity, credit_spread / US / 유가 급락; 에너지 하이일드 스프레드 확대 | 에너지 하이일드 노출 축소 검토 | 신용분석팀 | ⚠️ 원 사건 유형(geopolitical)이 전제에 없음 | OK | 합성 수용 |
| `PB-CMDTY-04` | 공급 차질로 원자재 가격이 급등하면 인플레이션 시나리오를 채권 전략에 반영한다. | geopolitical, supply_chain / commodity, rates / GLOBAL / 공급 차질에 따른 가격 급등 | 인플레이션 시나리오 반영 | 채권운용팀 |  | OK | 합성 수용 |
| `PB-CMDTY-05` | 원자재 수입 의존도가 높은 국가의 통화 약세 위험을 점검한다. | geopolitical, supply_chain / commodity, fx / KR, EM / 원자재 가격 급등 | 수입국 통화 위험 점검 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-CMDTY-06` | 원자재 가격 급등 시 원자재 상품 거래 상대방의 증거금 부담과 신용 위험을 점검한다. | geopolitical / commodity, counterparty / EU, GLOBAL / 증거금 급증 | 거래 상대방 증거금·신용 점검 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-CMDTY-07` | 곡물 가격 급등이 신흥국 물가에 미치는 영향을 점검한다. | geopolitical, supply_chain / commodity / EM / 곡물 수출 차질 | 신흥국 물가 영향 점검 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-CMDTY-08` | 원자재 가격이 안정되면 전술적 조정 포지션을 단계적으로 해소한다. | geopolitical, supply_chain, pandemic / commodity / - / 원자재 가격 안정 | 전술 포지션 단계적 해소 | 운용전략팀 |  | OK | 합성 수용 |

## PB-CPTY · 신용·거래상대방 부도 대응 절차
v1.0 · 2009년 · 원 사건 `gfc_2008` · 근거 data/source_notes/counterparty_gfc2008.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-CPTY-01` | 주요 거래상대방의 부도 또는 파산보호 신청이 확인되면 해당 상대방과의 전체 노출을 즉시 집계한다. | credit_event, banking_stress / counterparty / GLOBAL / 거래상대방 부도·파산보호 신청 | 상대방별 총노출 집계; CIO 보고 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-CPTY-02` | 부도 상대방과의 장외파생상품 계약은 ISDA 기본계약에 따라 조기종료 및 일괄정산 절차를 개시한다. | credit_event / counterparty / - / ISDA 기본계약 체결 상대방 부도 | 조기종료 통지; 일괄정산 금액 산정 | 법무팀 |  | OK | 합성 수용 |
| `PB-CPTY-03` | 수취 담보의 처분 가능성과 가치를 재평가하고 부족분은 추가 담보를 요구한다. | credit_event, banking_stress / counterparty, liquidity / - / 담보 가치 하락 | 담보 재평가; 추가 담보 요구 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-CPTY-04` | 투자은행 섹터의 신용부도스와프(CDS) 프리미엄이 급등하면 동일 섹터 상대방과의 신규 거래를 중단한다. | credit_event / counterparty, credit_spread / US, EU / 투자은행 CDS 급등 | 동일 섹터 상대방 신규 거래 중단 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-CPTY-05` | 부도 상대방이 발행한 채권·주식 보유분을 확인하고 회수 가능성을 평가한다. | credit_event / credit_spread / - / 부도 상대방 발행 증권 보유 | 보유 증권 확인; 회수율 추정 | 신용분석팀 |  | OK | 합성 수용 |
| `PB-CPTY-06` | 레포 거래 상대방의 신용도가 하락하면 레포 만기를 단축하고 상대방을 분산한다. | credit_event, liquidity_crisis, banking_stress / counterparty, liquidity / - / 레포 상대방 신용도 하락 | 레포 만기 단축; 상대방 분산 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-CPTY-07` | 가족계좌(family office) 등 고레버리지 상대방에 대한 프라임브로커 경유 간접 노출을 점검한다. | credit_event / counterparty, equity_vol / US / 고레버리지 투자자 마진콜 불이행 | 프라임브로커 경유 간접 노출 점검 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-CPTY-08` | 부도 상대방에 대한 손실 추정치를 분기 결산에 반영하도록 회계팀에 통보한다. | credit_event / counterparty / - / 손실 확정 또는 추정 가능 | 손실 추정치 산정; 회계팀 통보 | 재무팀 |  | OK | 합성 수용 |

## PB-FX · 환율 급변 대응 지침 (원화 약세)
v1.0 · 2009년 · 원 사건 `gfc_2008` · 근거 data/source_notes/fx_korea2008.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-FX-01` | 원/달러 환율이 단기간에 급등하면 외환 유동성 점검 회의를 소집한다. | fx_shock, credit_event, liquidity_crisis / fx, liquidity / KR / 원/달러 환율 급등 | 외환 유동성 점검 회의 소집 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-FX-02` | 국내 은행의 외화차입 상환 압력이 커지면 외화 조달 상대방과 만기 구조를 점검한다. | fx_shock, credit_event / fx, liquidity, counterparty / KR / 국내 은행 외화차입 상환 압력 | 외화 조달 만기 구조 점검 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-FX-03` | 외국인 증권자금 유출이 지속되면 원화 자산 비중과 환노출 한도를 재점검한다. | fx_shock, credit_event / fx, equity_vol / KR / 외국인 증권자금 유출 지속 | 환노출 한도 재점검 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-FX-04` | 환헤지 계약 만기 시 롤오버 비용이 급등하면 헤지 비율 하향 여부를 검토한다. | fx_shock / fx / KR / 스왑 포인트 급변 | 롤오버 비용 산정; 헤지 비율 검토 | 외환운용팀 | ⚠️ 원 사건 유형(credit_event)이 전제에 없음 | OK | 합성 수용 |
| `PB-FX-05` | 한미 통화스와프 등 정책 대응 발표 시 외환시장 안정 여부를 확인하고 헤지 정책을 정상화한다. | fx_shock, credit_event / fx, liquidity / KR, US / 중앙은행 간 통화스와프 체결 | 외환시장 안정 확인; 헤지 정책 정상화 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-FX-06` | 외화 키코(KIKO) 등 환율 연계 파생상품을 보유한 국내 기업에 대한 신용 노출을 점검한다. | fx_shock, credit_event / fx, credit_spread / KR / 환율 연계 파생상품 손실 확대 | 관련 기업 신용 노출 점검 | 신용분석팀 |  | OK | 합성 수용 |
| `PB-FX-07` | 원/달러 환율이 급등하면 외환 유동성 점검 회의를 소집하고 외화 현금 보유를 늘린다. | fx_shock / fx, liquidity / KR / 원/달러 환율 급등 | 외환 유동성 점검 회의 소집; 외화 현금 확대 | 외환운용팀 | ⚠️ 원 사건 유형(credit_event)이 전제에 없음 | OK | 합성 수용 |
| `PB-FX-08` | 해외 투자 자산의 원화 환산 평가액 변동을 일일 보고한다. | fx_shock / fx / KR, GLOBAL / 환율 급변 | 원화 환산 평가액 일일 보고 | 재무팀 | ⚠️ 원 사건 유형(credit_event)이 전제에 없음 | OK | 합성 수용 |

## PB-GEO · 지정학 위기·제재 대응 매뉴얼
v1.1 · 2022년 · 원 사건 `ru_ua_2022` · 근거 data/source_notes/geopolitical_ruua2022.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-GEO-01` | 군사 충돌 발생 시 분쟁 당사국 및 인접국 소재 자산의 노출을 국가별로 집계한다. | geopolitical / sanctions_trade, equity_vol / RU, UA, EU / 군사 충돌 발생 | 국가별 노출 집계; CIO 보고 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-GEO-02` | 제재 대상 국가·기관이 지정되면 해당 자산의 신규 매수를 금지하고 보유분은 준법감시팀 검토 후 처리한다. | geopolitical, regulatory / sanctions_trade / RU / 제재 대상 지정 | 신규 매수 금지; 보유분 준법 검토 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-GEO-03` | 제재 대상 은행이 국제 결제망에서 배제되면 해당 은행을 경유하는 결제·수탁 경로를 점검한다. | geopolitical / sanctions_trade, operational / RU / 국제 결제망(SWIFT) 배제 | 결제·수탁 경로 점검; 대체 경로 확보 | 운영지원팀 |  | OK | 합성 수용 |
| `PB-GEO-04` | 분쟁으로 에너지·곡물 공급 차질이 예상되면 원자재 가격 급등에 따른 포트폴리오 영향을 분석한다. | geopolitical, supply_chain / commodity, supply_chain / RU, UA, EU, GLOBAL / 에너지·곡물 수출국 분쟁 | 원자재 가격 시나리오 분석 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-GEO-05` | 제재로 거래가 중단된 자산은 공정가치 평가 방법을 재검토하고 평가위원회에 상정한다. | geopolitical, regulatory / sanctions_trade / RU / 거래 중단 자산 발생 | 공정가치 재평가; 평가위원회 상정 | 재무팀 |  | OK | 합성 수용 |
| `PB-GEO-06` | 위탁운용사에 제재 대상 자산 보유 현황과 처리 계획을 제출하도록 요청한다. | geopolitical / sanctions_trade, counterparty / RU / 위탁운용 자산 중 제재 대상 포함 가능 | 위탁운용사 보유 현황 요청 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-GEO-07` | 안전자산 선호로 달러 강세가 나타나면 환헤지 비율을 점검한다. | geopolitical / fx / GLOBAL / 달러 강세 | 환헤지 비율 점검 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-GEO-08` | 분쟁 장기화가 예상되면 국가 리스크 등급을 재산정하고 전략적 자산배분 회의에 상정한다. | geopolitical / sanctions_trade, commodity / GLOBAL / 분쟁 장기화 | 국가 리스크 등급 재산정; 자산배분 회의 상정 | 운용전략팀 |  | OK | 합성 수용 |

## PB-LIQ · 유동성 위기 대응 매뉴얼
v2.0 · 2020년 · 원 사건 `covid_2020` · 근거 data/source_notes/liquidity_covid2020.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-LIQ-01` | 전 자산군이 동반 하락하고 현금 확보 수요가 급증하면 즉시 유동성 점검 회의를 소집한다. | pandemic, liquidity_crisis / liquidity, equity_vol / GLOBAL / 주식·채권 동반 하락; VIX 급등 | 유동성 점검 회의 소집; 자산군별 처분 가능 금액 산출 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-LIQ-02` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | liquidity_crisis, pandemic / liquidity / - / 현금성 자산 비중 하한 미달 | 현금성 자산 비중 점검; 단기 국채·MMF 매수 | 자금운용팀 | ⚠️ 다른 조항과 문구 중복(의도된 중복인지 확인) | OK | 합성 수용 |
| `PB-LIQ-03` | 향후 3개월 내 예정된 출자 요청(capital call)과 지급 일정을 재점검하고 우선순위를 정한다. | liquidity_crisis, pandemic, credit_event / liquidity / - / 대체투자 출자 약정 존재 | capital call 일정 재점검; 지급 우선순위 결정 | 대체투자팀 |  | OK | 합성 수용 |
| `PB-LIQ-04` | 글로벌 달러 조달 여건이 악화되면 외화 유동성 한도를 하향하고 통화스와프 등 정책 지원 여부를 모니터링한다. | pandemic, liquidity_crisis / liquidity, fx / GLOBAL, US / 달러 조달 비용 급등; 중앙은행 스와프 라인 확대 | 외화 유동성 한도 하향; 정책 지원 모니터링 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-LIQ-05` | 리밸런싱 범위를 일시적으로 확대해 유동성이 낮은 시장에서의 강제 매도를 피한다. | pandemic, liquidity_crisis / liquidity, equity_vol / - / 시장 유동성 급감 | 리밸런싱 허용 범위 한시 확대 승인 요청 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-LIQ-06` | 봉쇄 조치로 실물 경기 급랭이 예상되면 경기민감 업종의 신규 매수를 보류한다. | pandemic / equity_vol, supply_chain / GLOBAL / 이동 제한·봉쇄 조치 시행 | 경기민감 업종 신규 매수 보류 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-LIQ-07` | 하이일드 채권 스프레드가 급등하면 투기등급 비중 한도 초과 여부를 일일 점검한다. | pandemic, credit_event, liquidity_crisis / credit_spread / US, GLOBAL / 하이일드 스프레드 급등 | 투기등급 비중 일일 점검; 한도 초과 시 보고 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-LIQ-08` | 중앙은행 유동성 공급이 발표되면 시장 안정 여부를 확인한 뒤 단계적으로 평상 한도로 복귀한다. | pandemic, liquidity_crisis / liquidity / - / 중앙은행 유동성 공급 발표 | 시장 안정 지표 확인; 한도 단계적 정상화 | 리스크관리팀 |  | OK | 합성 수용 |

## PB-MGR · 위탁운용사 사고 대응 절차
v1.2 · 2021년 · 원 사건 `optimus_2020` · 근거 data/source_notes/manager_incident_optimus.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-MGR-01` 🔒insurance | 위탁운용사의 환매중단 또는 운용 부실이 확인되면 해당 운용사에 위탁한 전체 자산을 즉시 동결 점검한다. | other, credit_event / operational, counterparty / - / 위탁운용사 환매중단·운용 부실 | 위탁 자산 동결 점검; CIO 보고 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-02` 🔒insurance | 수탁기관과 사무관리회사에 실제 편입 자산 내역을 독립적으로 확인 요청한다. | other, credit_event / operational / - / 운용사 보고 자산과 실제 자산 불일치 의심 | 수탁기관·사무관리사 독립 확인 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-03` 🔒insurance | 위기 국면에서 위탁운용사의 레버리지와 파생상품 노출이 한도를 넘는지 점검한다. | liquidity_crisis, credit_event, banking_stress, pandemic / counterparty, liquidity / - / 시장 급변 | 위탁운용사 레버리지 점검 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-04` | 위탁운용사 핵심 인력 이탈이나 감독기관 제재가 확인되면 운용사 평가를 즉시 재실시한다. | regulatory, other / operational / - / 핵심 인력 이탈; 감독기관 제재 | 운용사 수시 평가 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-05` 🔒insurance | 손실 회수를 위해 판매사·수탁사·운용사의 책임 관계를 법무팀이 검토한다. | other, regulatory / operational, counterparty / KR / 투자 손실 발생 | 책임 관계 법률 검토 | 법무팀 |  | OK | 합성 수용 |
| `PB-MGR-06` | 위탁 자산의 일부를 다른 운용사로 이관하는 비상 이관 계획을 가동한다. | other / operational / - / 운용사 운용 지속 불가 | 비상 이관 계획 가동 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-07` | 위탁운용사 사고 내용과 조치 결과를 투자위원회에 보고한다. | other, regulatory / operational / - / 위탁운용사 사고 발생 | 투자위원회 보고 | 위탁운용팀 |  | OK | 합성 수용 |
| `PB-MGR-08` | 유사 전략을 운용하는 다른 위탁운용사에 대해 동일 위험 여부를 점검한다. | other, credit_event / operational, counterparty / - / 특정 전략에서 사고 발생 | 유사 전략 운용사 점검 | 위탁운용팀 |  | OK | 합성 수용 |

## PB-RATE · 금리 급등 대응 지침
v1.0 · 2022년 · 원 사건 `rate_hike_2022` · 근거 data/source_notes/rates_2022.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-RATE-01` | 장기 국채금리가 단기간 급등하면 채권 포트폴리오의 듀레이션과 평가손실을 일일 산출한다. | rate_shock / rates / US, KR / 장기 금리 급등 | 듀레이션·평가손실 일일 산출 | 채권운용팀 |  | OK | 합성 수용 |
| `PB-RATE-02` | 금리 상승으로 주식·채권 상관관계가 양(+)으로 바뀌면 분산 효과 저하를 반영해 리스크 한도를 재산정한다. | rate_shock / rates, equity_vol / GLOBAL / 주식·채권 동반 하락 | 상관관계 재추정; 리스크 한도 재산정 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-RATE-03` | 변동금리 차입 비중이 높은 기업의 신용 노출을 점검한다. | rate_shock, credit_event / rates, credit_spread / - / 금리 상승 지속 | 변동금리 차입 기업 노출 점검 | 신용분석팀 |  | OK | 합성 수용 |
| `PB-RATE-04` | 부동산·인프라 대체투자 자산의 할인율을 재검토하고 평가 반영 시점을 정한다. | rate_shock / rates / - / 할인율 상승 | 할인율 재검토; 평가 반영 시점 결정 | 대체투자팀 |  | OK | 합성 수용 |
| `PB-RATE-05` | 중앙은행 통화정책 회의 일정과 시장 기대 금리 경로를 추적한다. | rate_shock / rates / US, KR / 통화정책 불확실성 | 정책회의 일정·기대 경로 추적 | 채권운용팀 |  | OK | 합성 수용 |
| `PB-RATE-06` | 장단기 금리 역전이 지속되면 경기 침체 시나리오를 자산배분 회의에 상정한다. | rate_shock / rates / US / 장단기 금리 역전 지속 | 침체 시나리오 상정 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-RATE-07` | 금리 상승기에 보유채권 평가손실이 큰 금융기관과의 거래 노출을 점검한다. | rate_shock, banking_stress / rates, counterparty / - / 금융기관 보유채권 평가손실 확대 | 금융기관 거래 노출 점검 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-RATE-08` | 내외 금리차 확대로 원화 약세가 나타나면 환헤지 비용을 재산정한다. | rate_shock, fx_shock / rates, fx / KR, US / 내외 금리차 확대 | 환헤지 비용 재산정 | 외환운용팀 |  | OK | 합성 수용 |

## PB-REG · 위기 시 규제 보고·공시 절차
v3.0 · 2024년 · 원 사건 `none` · 근거 data/source_notes/regulatory_reporting.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-REG-01` 🔒regulatory | 중대한 손실 또는 한도 위반이 발생하면 정해진 기한 내에 감독기관에 보고한다. | - / - / - / 중대 손실 또는 한도 위반 | 감독기관 기한 내 보고 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-REG-02` 🔒regulatory | 공매도 금지 등 시장 조치가 시행되면 위탁운용사와 내부 운용의 준수 여부를 확인한다. | regulatory, pandemic, liquidity_crisis / equity_vol / KR / 공매도 금지 등 시장 조치 시행 | 준수 여부 확인; 위탁운용사 통보 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-REG-03` 🔒regulatory | 제재 대상 지정 시 관련 법령에 따른 보고 의무를 확인하고 이행한다. | geopolitical, regulatory / sanctions_trade / - / 제재 대상 지정 | 제재 관련 보고 의무 이행 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-REG-04` 🔒regulatory | 위기 대응을 위한 한도 예외 승인은 사후 7일 이내에 이사회(또는 위원회)에 보고한다. | - / - / - / 한도 예외 승인 | 이사회 사후 보고 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-REG-05` 🔒regulatory | 위기 대응 과정의 의사결정 기록을 보존 기한 동안 보관한다. | - / operational / - / 위기 대응 의사결정 | 의사결정 기록 보관 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-REG-06` | 외부 공시 대상 사안은 공시 담당 부서의 검토를 거쳐 공시한다. | - / - / - / 공시 대상 사안 발생 | 공시 검토·실행 | 준법감시팀 | ⚠️ 전제 사건유형 없음, 전제 채널 없음 | OK | 합성 수용 |
| `PB-REG-07` | 개인정보·내부정보가 포함된 위기 대응 자료의 외부 공유를 제한한다. | - / operational / - / 위기 대응 자료 공유 | 외부 공유 제한 | 준법감시팀 | ⚠️ 전제 사건유형 없음 | OK | 합성 수용 |
| `PB-REG-08` 🔒regulatory | 위기 종료 후 30일 이내에 사후보고서를 작성해 이사회에 보고한다. | - / - / - / 위기 종료 | 사후보고서 작성; 이사회 보고 | 리스크관리팀 |  | OK | 합성 수용 |

## PB-STFM · 국내 단기자금시장 경색 대응 지침
v1.0 · 2022년 · 원 사건 `legoland_2022` · 근거 data/source_notes/stfm_legoland2022.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-STFM-01` | 지자체·공기업 보증 채무의 부도 또는 회생 신청이 발생하면 관련 CP·ABCP 보유 현황을 즉시 집계한다. | liquidity_crisis, credit_event / liquidity, credit_spread / KR / 지자체 보증 채무 부도; 공공 보증 신뢰 훼손 | CP·ABCP 보유 현황 집계 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-STFM-02` | CP 금리가 급등하고 차환 발행이 어려워지면 단기물 신규 매수를 보류하고 만기 도래분을 현금화한다. | liquidity_crisis / liquidity, credit_spread / KR / CP 금리 급등; 차환 발행 곤란 | 단기물 신규 매수 보류; 만기분 현금화 | 자금운용팀 |  | OK | 합성 수용 |
| `PB-STFM-03` | 부동산 PF 유동화증권 노출을 증권사·건설사별로 점검한다. | liquidity_crisis, credit_event / credit_spread, counterparty / KR / 부동산 PF 우발채무 확대 | PF 유동화증권 노출 점검 | 신용분석팀 |  | OK | 합성 수용 |
| `PB-STFM-04` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | liquidity_crisis / liquidity / KR / 현금성 자산 비중 하한 미달 | 현금성 자산 비중 점검; 단기 국채·MMF 매수 | 자금운용팀 | ⚠️ 다른 조항과 문구 중복(의도된 중복인지 확인) | OK | 합성 수용 |
| `PB-STFM-05` | 정부의 채권시장안정펀드·회사채 매입 프로그램 발표 시 시장 금리 안정 여부를 확인한다. | liquidity_crisis / liquidity, credit_spread / KR / 정부 유동성 공급 프로그램 발표 | 시장 금리 안정 확인 | 채권운용팀 |  | OK | 합성 수용 |
| `PB-STFM-06` | 증권사의 유동성 부족 징후가 있으면 해당 증권사와의 레포·RP 거래 노출을 점검한다. | liquidity_crisis / counterparty, liquidity / KR / 증권사 유동성 부족 | 증권사 레포·RP 노출 점검 | 거래상대방관리팀 |  | OK | 합성 수용 |
| `PB-STFM-07` | 공사채·은행채 발행이 늘어 회사채 수요를 구축하는지 발행시장을 모니터링한다. | liquidity_crisis / credit_spread / KR / 공공·은행채 발행 급증 | 발행시장 모니터링 | 채권운용팀 |  | OK | 합성 수용 |
| `PB-STFM-08` | 한국은행의 적격담보 확대 등 유동성 조치가 발표되면 담보로 활용 가능한 보유 채권을 확인한다. | liquidity_crisis / liquidity / KR / 중앙은행 적격담보 확대 | 담보 활용 가능 채권 확인 | 자금운용팀 |  | OK | 합성 수용 |

## PB-TRADE · 무역정책 충격 대응 지침
v1.0 · 2025년 · 원 사건 `tariff_2025` · 근거 data/source_notes/trade_tariff2025.md

| 조항 | 내용 | 전제 (사건유형 / 채널 / 지역 / 조건) | 조치 | 담당 | 자동 점검 | 검수 (OK / 수정 / 삭제) | 의견 |
|---|---|---|---|---|---|---|---|
| `PB-TRADE-01` | 대규모 관세 부과가 발표되면 관세 대상국 소재 기업과 수출 의존 업종의 노출을 집계한다. | trade_policy / sanctions_trade, equity_vol / US, CN, KR, GLOBAL / 대규모 관세 부과 발표 | 관세 대상국·업종 노출 집계 | 리스크관리팀 |  | OK | 합성 수용 |
| `PB-TRADE-02` | 관세로 공급망 재편이 예상되면 자동차·반도체 등 대미 수출 업종의 실적 영향을 분석한다. | trade_policy, supply_chain / supply_chain, sanctions_trade / KR, CN / 공급망 재편 | 업종별 실적 영향 분석 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-TRADE-03` | 관세 발효일과 유예 조치를 추적해 시나리오별 대응안을 갱신한다. | trade_policy / sanctions_trade / US / 관세 발효·유예 일정 변동 | 관세 일정 추적; 시나리오 갱신 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-TRADE-04` | 무역 갈등으로 신흥국 통화가 약세를 보이면 신흥국 자산의 환노출을 점검한다. | trade_policy, fx_shock / fx / EM, CN, KR / 신흥국 통화 약세 | 신흥국 환노출 점검 | 외환운용팀 |  | OK | 합성 수용 |
| `PB-TRADE-05` | 주식시장 변동성이 급등하면 리밸런싱 실행을 분할하고 거래 비용을 점검한다. | trade_policy, geopolitical / equity_vol / GLOBAL / 주식 변동성 급등 | 리밸런싱 분할 실행; 거래 비용 점검 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-TRADE-06` | 보복 관세가 예고되면 상대국 수입 의존 업종의 2차 영향을 점검한다. | trade_policy / sanctions_trade, supply_chain / CN, EU / 보복 관세 예고 | 2차 영향 업종 점검 | 운용전략팀 |  | OK | 합성 수용 |
| `PB-TRADE-07` | 관세 관련 법적 근거와 소송 동향을 준법감시팀이 정리해 보고한다. | trade_policy, regulatory / sanctions_trade / US / 관세 법적 다툼 | 법적 근거·소송 동향 보고 | 준법감시팀 |  | OK | 합성 수용 |
| `PB-TRADE-08` | 관세에 따른 물가·금리 경로 변화를 반영해 채권 듀레이션 전략을 재검토한다. | trade_policy, rate_shock / rates / US / 관세발 물가 상승 우려 | 듀레이션 전략 재검토 | 채권운용팀 |  | OK | 합성 수용 |
