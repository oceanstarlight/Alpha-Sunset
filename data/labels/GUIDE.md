# 라벨 작성 참고표

> 라벨은 사람이 직접 판단해서 쓴다. 에이전트 판정 결과(`data/backtest/`)는 보지 말고 작성해야 채점이 순환되지 않는다.

## 작성 순서 (사건 1개당 10~20분)
1. `data/labels/{event_id}.json` 열기 (빈 틀이 이미 있음)
2. `reaction_date`: 기관이 늦어도 이날까지는 대응을 시작했어야 한다고 보는 날짜
3. `expected_docs`: 이 사건에 꼭 꺼내 봐야 할 문서 1~3개 (상위 3개 안에 들어야 정답)
4. `expected_inapplicable_clauses`: 후보로 나오겠지만 이 사건엔 **맞지 않는** 조항 (사건당 3~8개 권장)
5. `expected_gap_channels`: 사건 채널 중 **어떤 문서도 제대로 다루지 못하는** 채널 (없으면 빈 목록 `[]`)
6. `expected_exposure_paths`: 노출 상위에 꼭 나와야 할 포트폴리오 노드 id (2~5개 권장, gfc_2008은 `[]`)
7. `notes`: 판단 근거 한두 줄
8. 저장 후 `python -m scripts.validate_data` 로 오타 확인

## 채널 값
`liquidity`, `credit_spread`, `counterparty`, `fx`, `commodity`, `supply_chain`, `rates`, `equity_vol`, `sanctions_trade`, `operational`

## 사건
- **gfc_2008** (2008-09-15) 2008 리먼 브라더스 파산과 한국 외환시장 불안 — 채널: counterparty, liquidity, credit_spread, fx, equity_vol / 지역: US, KR, GLOBAL
- **covid_2020** (2020-03-11) 2020 코로나19 팬데믹 충격과 한국 공매도 금지 — 채널: equity_vol, liquidity, credit_spread, fx, commodity, operational, supply_chain / 지역: GLOBAL, KR, US, CN
- **ru_ua_2022** (2022-02-24) 2022 러시아-우크라이나 전쟁과 대러 제재 — 채널: sanctions_trade, commodity, equity_vol, fx, counterparty / 지역: RU, UA, EU, GLOBAL
- **legoland_2022** (2022-09-28) 2022 레고랜드 사태와 국내 단기자금시장 경색 — 채널: liquidity, credit_spread, counterparty / 지역: KR
- **svb_2023** (2023-03-10) 2023 실리콘밸리은행(SVB) 파산 — 채널: liquidity, counterparty, rates, equity_vol / 지역: US
- **tariff_2025** (2025-04-02) 2025 미국 상호관세 충격 — 채널: sanctions_trade, supply_chain, equity_vol, fx / 지역: US, CN, KR, GLOBAL

## 포트폴리오 노드 (`expected_exposure_paths`)
| id | 이름 | 유형 | 지역 | 업종 | 자산군 |
|---|---|---|---|---|---|
| `D-UST` | 미국 국채 (7~10년) | direct | US | sovereign | govt_bond |
| `D-KTB` | 한국 국고채 | direct | KR | sovereign | govt_bond |
| `D-USEQ` | 미국 대형주 ETF | direct | US | broad_market | equity |
| `D-KREQ` | 한국 주식 ETF | direct | KR | broad_market, semiconductors, autos | equity |
| `D-MMF` | 국내 MMF·단기자금 | direct | KR | broker_dealers, banks | money_market, commercial_paper |
| `D-RE` | 국내 부동산 펀드 | direct | KR | real_estate | real_estate |
| `M-HANBIT` | 한빛자산운용 (미국 지역은행 전략) | manager | US | regional_banks, banks | equity |
| `M-CHEONGRAM` | 청람인베스트 (신흥국 달러채권) | manager | EM, KR, CN | sovereign | em_bond |
| `M-DAON` | 다온캐피탈 (미국 하이일드) | manager | US | energy, telecom, consumer | high_yield, corporate_bond |
| `M-NURI` | 누리에셋 (미국 에너지주) | manager | US | energy | equity, commodity |
| `M-SEOGYEONG` | 서경파트너스 (중국 주식) | manager | CN | technology, consumer, manufacturing | equity |
| `M-MIR` | 미르글로벌 (유럽 주식) | manager | EU | banks, energy, manufacturing | equity |
| `C-ATLAS` | 아틀라스 글로벌증권 (미국 투자은행) | counterparty | US, GLOBAL | broker_dealers | derivatives |
| `C-RHEIN` | 라인방크 (유럽 은행) | counterparty | EU | banks | derivatives, fx |
| `C-PACIFICA` | 퍼시피카 뱅크 (미국 지역은행) | counterparty | US | regional_banks, banks | derivatives |
| `C-HANGANG` | 한강증권 (국내 증권사) | counterparty | KR | broker_dealers, real_estate | repo, commercial_paper |
| `C-SEORAE` | 서래은행 (국내 은행) | counterparty | KR | banks | repo, fx |

## 문서·조항 (`expected_docs`, `expected_inapplicable_clauses`)

### `PB-BANK` 은행 시스템 위기 대응 지침 (v1.0, 2023, 원 사건 svb_2023)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-BANK-01` | 예치 은행의 폐쇄 또는 뱅크런 징후가 확인되면 해당 은행 예금·결제계좌 잔액을 즉시 확인한다. | banking_stress | counterparty, liquidity |
| `PB-BANK-02` | 단일 은행 예치 한도를 초과한 예금은 신용등급이 높은 복수 은행으로 분산한다. | banking_stress | counterparty |
| `PB-BANK-03` | 보유 채권의 미실현 평가손실이 큰 지역은행을 식별하고 해당 은행 주식·채권 노출을 점검한다. | banking_stress, rate_shock | rates, counterparty |
| `PB-BANK-04` | 정부의 예금 전액 보호 또는 긴급 대출 프로그램 발표 시 시장 안정 여부를 확인하고 추가 매도를 보류한다. | banking_stress | liquidity |
| `PB-BANK-05` | 은행 섹터 주가 변동성이 급등하면 은행 섹터 비중을 벤치마크 대비 중립 이하로 조정한다. | banking_stress | equity_vol |
| `PB-BANK-06` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | banking_stress, liquidity_crisis | liquidity |
| `PB-BANK-07` | 벤처·기술 기업 예금 비중이 높은 은행과 거래하는 위탁운용사에 결제계좌 현황을 확인 요청한다. | banking_stress | counterparty, operational |
| `PB-BANK-08` | 은행 위기가 해외 은행으로 전이되는지 확인하기 위해 주요 은행 CDS와 단기자금 금리를 일일 모니터링한다. | banking_stress | credit_spread, liquidity |

### `PB-BCP` 팬데믹 업무연속성계획(BCP) (v1.0, 2020, 원 사건 covid_2020)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-BCP-01` | 감염병 확산으로 사무실 출입이 제한되면 핵심 운용 인력의 분산·재택근무 체계를 가동한다. | pandemic | operational |
| `PB-BCP-02` | 원격 접속 환경에서도 매매·결제 시스템이 정상 작동하는지 일일 점검한다. | pandemic | operational |
| `PB-BCP-03` | 핵심 업무별 대체 인력을 지정하고 결재 권한 위임표를 갱신한다. | pandemic, other | operational |
| `PB-BCP-04` | 위탁운용사와 수탁기관의 업무연속성 계획 가동 여부를 확인한다. | pandemic | operational, counterparty |
| `PB-BCP-05` | 해외 사무소 소재국의 이동 제한 조치를 모니터링하고 출장을 중단한다. | pandemic | operational |
| `PB-BCP-06` | 원격 근무 중 정보보안 사고를 막기 위해 접속 기록을 점검한다. | pandemic | operational |
| `PB-BCP-07` | 임직원 확진 시 접촉자 분리와 사무실 방역 절차를 시행한다. | pandemic | operational |
| `PB-BCP-08` | 투자위원회는 화상회의로 개최하고 의결 기록을 전자 보관한다. | pandemic | operational |

### `PB-CMDTY` 원자재 가격 충격 대응 지침 (v1.0, 2022, 원 사건 ru_ua_2022)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-CMDTY-01` | 유가가 단기간 급등하거나 급락하면 에너지 업종과 원자재 관련 자산의 노출을 집계한다. | geopolitical, supply_chain, pandemic | commodity |
| `PB-CMDTY-02` | 선물 만기 직전 극단적 가격 왜곡이 나타나면 원자재 선물·ETF의 롤오버 일정을 점검한다. | pandemic, supply_chain | commodity, liquidity |
| `PB-CMDTY-03` | 유가 급락으로 에너지 기업의 하이일드 채권 부도 위험이 커지면 해당 노출을 줄인다. | pandemic, credit_event | commodity, credit_spread |
| `PB-CMDTY-04` | 공급 차질로 원자재 가격이 급등하면 인플레이션 시나리오를 채권 전략에 반영한다. | geopolitical, supply_chain | commodity, rates |
| `PB-CMDTY-05` | 원자재 수입 의존도가 높은 국가의 통화 약세 위험을 점검한다. | geopolitical, supply_chain | commodity, fx |
| `PB-CMDTY-06` | 원자재 가격 급등 시 원자재 상품 거래 상대방의 증거금 부담과 신용 위험을 점검한다. | geopolitical | commodity, counterparty |
| `PB-CMDTY-07` | 곡물 가격 급등이 신흥국 물가에 미치는 영향을 점검한다. | geopolitical, supply_chain | commodity |
| `PB-CMDTY-08` | 원자재 가격이 안정되면 전술적 조정 포지션을 단계적으로 해소한다. | geopolitical, supply_chain, pandemic | commodity |

### `PB-CPTY` 신용·거래상대방 부도 대응 절차 (v1.0, 2009, 원 사건 gfc_2008)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-CPTY-01` | 주요 거래상대방의 부도 또는 파산보호 신청이 확인되면 해당 상대방과의 전체 노출을 즉시 집계한다. | credit_event, banking_stress | counterparty |
| `PB-CPTY-02` | 부도 상대방과의 장외파생상품 계약은 ISDA 기본계약에 따라 조기종료 및 일괄정산 절차를 개시한다. | credit_event | counterparty |
| `PB-CPTY-03` | 수취 담보의 처분 가능성과 가치를 재평가하고 부족분은 추가 담보를 요구한다. | credit_event, banking_stress | counterparty, liquidity |
| `PB-CPTY-04` | 투자은행 섹터의 신용부도스와프(CDS) 프리미엄이 급등하면 동일 섹터 상대방과의 신규 거래를 중단한다. | credit_event | counterparty, credit_spread |
| `PB-CPTY-05` | 부도 상대방이 발행한 채권·주식 보유분을 확인하고 회수 가능성을 평가한다. | credit_event | credit_spread |
| `PB-CPTY-06` | 레포 거래 상대방의 신용도가 하락하면 레포 만기를 단축하고 상대방을 분산한다. | credit_event, liquidity_crisis, banking_stress | counterparty, liquidity |
| `PB-CPTY-07` | 가족계좌(family office) 등 고레버리지 상대방에 대한 프라임브로커 경유 간접 노출을 점검한다. | credit_event | counterparty, equity_vol |
| `PB-CPTY-08` | 부도 상대방에 대한 손실 추정치를 분기 결산에 반영하도록 회계팀에 통보한다. | credit_event | counterparty |

### `PB-FX` 환율 급변 대응 지침 (원화 약세) (v1.0, 2009, 원 사건 gfc_2008)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-FX-01` | 원/달러 환율이 단기간에 급등하면 외환 유동성 점검 회의를 소집한다. | fx_shock, credit_event, liquidity_crisis | fx, liquidity |
| `PB-FX-02` | 국내 은행의 외화차입 상환 압력이 커지면 외화 조달 상대방과 만기 구조를 점검한다. | fx_shock, credit_event | fx, liquidity, counterparty |
| `PB-FX-03` | 외국인 증권자금 유출이 지속되면 원화 자산 비중과 환노출 한도를 재점검한다. | fx_shock, credit_event | fx, equity_vol |
| `PB-FX-04` | 환헤지 계약 만기 시 롤오버 비용이 급등하면 헤지 비율 하향 여부를 검토한다. | fx_shock | fx |
| `PB-FX-05` | 한미 통화스와프 등 정책 대응 발표 시 외환시장 안정 여부를 확인하고 헤지 정책을 정상화한다. | fx_shock, credit_event | fx, liquidity |
| `PB-FX-06` | 외화 키코(KIKO) 등 환율 연계 파생상품을 보유한 국내 기업에 대한 신용 노출을 점검한다. | fx_shock, credit_event | fx, credit_spread |
| `PB-FX-07` | 원/달러 환율이 급등하면 외환 유동성 점검 회의를 소집하고 외화 현금 보유를 늘린다. | fx_shock | fx, liquidity |
| `PB-FX-08` | 해외 투자 자산의 원화 환산 평가액 변동을 일일 보고한다. | fx_shock | fx |

### `PB-GEO` 지정학 위기·제재 대응 매뉴얼 (v1.1, 2022, 원 사건 ru_ua_2022)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-GEO-01` | 군사 충돌 발생 시 분쟁 당사국 및 인접국 소재 자산의 노출을 국가별로 집계한다. | geopolitical | sanctions_trade, equity_vol |
| `PB-GEO-02` | 제재 대상 국가·기관이 지정되면 해당 자산의 신규 매수를 금지하고 보유분은 준법감시팀 검토 후 처리한다. | geopolitical, regulatory | sanctions_trade |
| `PB-GEO-03` | 제재 대상 은행이 국제 결제망에서 배제되면 해당 은행을 경유하는 결제·수탁 경로를 점검한다. | geopolitical | sanctions_trade, operational |
| `PB-GEO-04` | 분쟁으로 에너지·곡물 공급 차질이 예상되면 원자재 가격 급등에 따른 포트폴리오 영향을 분석한다. | geopolitical, supply_chain | commodity, supply_chain |
| `PB-GEO-05` | 제재로 거래가 중단된 자산은 공정가치 평가 방법을 재검토하고 평가위원회에 상정한다. | geopolitical, regulatory | sanctions_trade |
| `PB-GEO-06` | 위탁운용사에 제재 대상 자산 보유 현황과 처리 계획을 제출하도록 요청한다. | geopolitical | sanctions_trade, counterparty |
| `PB-GEO-07` | 안전자산 선호로 달러 강세가 나타나면 환헤지 비율을 점검한다. | geopolitical | fx |
| `PB-GEO-08` | 분쟁 장기화가 예상되면 국가 리스크 등급을 재산정하고 전략적 자산배분 회의에 상정한다. | geopolitical | sanctions_trade, commodity |

### `PB-LIQ` 유동성 위기 대응 매뉴얼 (v2.0, 2020, 원 사건 covid_2020)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-LIQ-01` | 전 자산군이 동반 하락하고 현금 확보 수요가 급증하면 즉시 유동성 점검 회의를 소집한다. | pandemic, liquidity_crisis | liquidity, equity_vol |
| `PB-LIQ-02` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | liquidity_crisis, pandemic | liquidity |
| `PB-LIQ-03` | 향후 3개월 내 예정된 출자 요청(capital call)과 지급 일정을 재점검하고 우선순위를 정한다. | liquidity_crisis, pandemic, credit_event | liquidity |
| `PB-LIQ-04` | 글로벌 달러 조달 여건이 악화되면 외화 유동성 한도를 하향하고 통화스와프 등 정책 지원 여부를 모니터링한다. | pandemic, liquidity_crisis | liquidity, fx |
| `PB-LIQ-05` | 리밸런싱 범위를 일시적으로 확대해 유동성이 낮은 시장에서의 강제 매도를 피한다. | pandemic, liquidity_crisis | liquidity, equity_vol |
| `PB-LIQ-06` | 봉쇄 조치로 실물 경기 급랭이 예상되면 경기민감 업종의 신규 매수를 보류한다. | pandemic | equity_vol, supply_chain |
| `PB-LIQ-07` | 하이일드 채권 스프레드가 급등하면 투기등급 비중 한도 초과 여부를 일일 점검한다. | pandemic, credit_event, liquidity_crisis | credit_spread |
| `PB-LIQ-08` | 중앙은행 유동성 공급이 발표되면 시장 안정 여부를 확인한 뒤 단계적으로 평상 한도로 복귀한다. | pandemic, liquidity_crisis | liquidity |

### `PB-MGR` 위탁운용사 사고 대응 절차 (v1.2, 2021, 원 사건 optimus_2020)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-MGR-01` 🔒 | 위탁운용사의 환매중단 또는 운용 부실이 확인되면 해당 운용사에 위탁한 전체 자산을 즉시 동결 점검한다. | other, credit_event | operational, counterparty |
| `PB-MGR-02` 🔒 | 수탁기관과 사무관리회사에 실제 편입 자산 내역을 독립적으로 확인 요청한다. | other, credit_event | operational |
| `PB-MGR-03` 🔒 | 위기 국면에서 위탁운용사의 레버리지와 파생상품 노출이 한도를 넘는지 점검한다. | liquidity_crisis, credit_event, banking_stress, pandemic | counterparty, liquidity |
| `PB-MGR-04` | 위탁운용사 핵심 인력 이탈이나 감독기관 제재가 확인되면 운용사 평가를 즉시 재실시한다. | regulatory, other | operational |
| `PB-MGR-05` 🔒 | 손실 회수를 위해 판매사·수탁사·운용사의 책임 관계를 법무팀이 검토한다. | other, regulatory | operational, counterparty |
| `PB-MGR-06` | 위탁 자산의 일부를 다른 운용사로 이관하는 비상 이관 계획을 가동한다. | other | operational |
| `PB-MGR-07` | 위탁운용사 사고 내용과 조치 결과를 투자위원회에 보고한다. | other, regulatory | operational |
| `PB-MGR-08` | 유사 전략을 운용하는 다른 위탁운용사에 대해 동일 위험 여부를 점검한다. | other, credit_event | operational, counterparty |

### `PB-RATE` 금리 급등 대응 지침 (v1.0, 2022, 원 사건 rate_hike_2022)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-RATE-01` | 장기 국채금리가 단기간 급등하면 채권 포트폴리오의 듀레이션과 평가손실을 일일 산출한다. | rate_shock | rates |
| `PB-RATE-02` | 금리 상승으로 주식·채권 상관관계가 양(+)으로 바뀌면 분산 효과 저하를 반영해 리스크 한도를 재산정한다. | rate_shock | rates, equity_vol |
| `PB-RATE-03` | 변동금리 차입 비중이 높은 기업의 신용 노출을 점검한다. | rate_shock, credit_event | rates, credit_spread |
| `PB-RATE-04` | 부동산·인프라 대체투자 자산의 할인율을 재검토하고 평가 반영 시점을 정한다. | rate_shock | rates |
| `PB-RATE-05` | 중앙은행 통화정책 회의 일정과 시장 기대 금리 경로를 추적한다. | rate_shock | rates |
| `PB-RATE-06` | 장단기 금리 역전이 지속되면 경기 침체 시나리오를 자산배분 회의에 상정한다. | rate_shock | rates |
| `PB-RATE-07` | 금리 상승기에 보유채권 평가손실이 큰 금융기관과의 거래 노출을 점검한다. | rate_shock, banking_stress | rates, counterparty |
| `PB-RATE-08` | 내외 금리차 확대로 원화 약세가 나타나면 환헤지 비용을 재산정한다. | rate_shock, fx_shock | rates, fx |

### `PB-REG` 위기 시 규제 보고·공시 절차 (v3.0, 2024, 원 사건 none)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-REG-01` 🔒 | 중대한 손실 또는 한도 위반이 발생하면 정해진 기한 내에 감독기관에 보고한다. | - | - |
| `PB-REG-02` 🔒 | 공매도 금지 등 시장 조치가 시행되면 위탁운용사와 내부 운용의 준수 여부를 확인한다. | regulatory, pandemic, liquidity_crisis | equity_vol |
| `PB-REG-03` 🔒 | 제재 대상 지정 시 관련 법령에 따른 보고 의무를 확인하고 이행한다. | geopolitical, regulatory | sanctions_trade |
| `PB-REG-04` 🔒 | 위기 대응을 위한 한도 예외 승인은 사후 7일 이내에 이사회(또는 위원회)에 보고한다. | - | - |
| `PB-REG-05` 🔒 | 위기 대응 과정의 의사결정 기록을 보존 기한 동안 보관한다. | - | operational |
| `PB-REG-06` | 외부 공시 대상 사안은 공시 담당 부서의 검토를 거쳐 공시한다. | - | - |
| `PB-REG-07` | 개인정보·내부정보가 포함된 위기 대응 자료의 외부 공유를 제한한다. | - | operational |
| `PB-REG-08` 🔒 | 위기 종료 후 30일 이내에 사후보고서를 작성해 이사회에 보고한다. | - | - |

### `PB-STFM` 국내 단기자금시장 경색 대응 지침 (v1.0, 2022, 원 사건 legoland_2022)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-STFM-01` | 지자체·공기업 보증 채무의 부도 또는 회생 신청이 발생하면 관련 CP·ABCP 보유 현황을 즉시 집계한다. | liquidity_crisis, credit_event | liquidity, credit_spread |
| `PB-STFM-02` | CP 금리가 급등하고 차환 발행이 어려워지면 단기물 신규 매수를 보류하고 만기 도래분을 현금화한다. | liquidity_crisis | liquidity, credit_spread |
| `PB-STFM-03` | 부동산 PF 유동화증권 노출을 증권사·건설사별로 점검한다. | liquidity_crisis, credit_event | credit_spread, counterparty |
| `PB-STFM-04` | 현금성 자산 비중이 목표 하한 아래로 내려가면 단기 국채와 MMF로 우선 보충한다. | liquidity_crisis | liquidity |
| `PB-STFM-05` | 정부의 채권시장안정펀드·회사채 매입 프로그램 발표 시 시장 금리 안정 여부를 확인한다. | liquidity_crisis | liquidity, credit_spread |
| `PB-STFM-06` | 증권사의 유동성 부족 징후가 있으면 해당 증권사와의 레포·RP 거래 노출을 점검한다. | liquidity_crisis | counterparty, liquidity |
| `PB-STFM-07` | 공사채·은행채 발행이 늘어 회사채 수요를 구축하는지 발행시장을 모니터링한다. | liquidity_crisis | credit_spread |
| `PB-STFM-08` | 한국은행의 적격담보 확대 등 유동성 조치가 발표되면 담보로 활용 가능한 보유 채권을 확인한다. | liquidity_crisis | liquidity |

### `PB-TRADE` 무역정책 충격 대응 지침 (v1.0, 2025, 원 사건 tariff_2025)
| 조항 | 내용 | 전제 사건유형 | 전제 채널 |
|---|---|---|---|
| `PB-TRADE-01` | 대규모 관세 부과가 발표되면 관세 대상국 소재 기업과 수출 의존 업종의 노출을 집계한다. | trade_policy | sanctions_trade, equity_vol |
| `PB-TRADE-02` | 관세로 공급망 재편이 예상되면 자동차·반도체 등 대미 수출 업종의 실적 영향을 분석한다. | trade_policy, supply_chain | supply_chain, sanctions_trade |
| `PB-TRADE-03` | 관세 발효일과 유예 조치를 추적해 시나리오별 대응안을 갱신한다. | trade_policy | sanctions_trade |
| `PB-TRADE-04` | 무역 갈등으로 신흥국 통화가 약세를 보이면 신흥국 자산의 환노출을 점검한다. | trade_policy, fx_shock | fx |
| `PB-TRADE-05` | 주식시장 변동성이 급등하면 리밸런싱 실행을 분할하고 거래 비용을 점검한다. | trade_policy, geopolitical | equity_vol |
| `PB-TRADE-06` | 보복 관세가 예고되면 상대국 수입 의존 업종의 2차 영향을 점검한다. | trade_policy | sanctions_trade, supply_chain |
| `PB-TRADE-07` | 관세 관련 법적 근거와 소송 동향을 준법감시팀이 정리해 보고한다. | trade_policy, regulatory | sanctions_trade |
| `PB-TRADE-08` | 관세에 따른 물가·금리 경로 변화를 반영해 채권 듀레이션 전략을 재검토한다. | trade_policy, rate_shock | rates |
