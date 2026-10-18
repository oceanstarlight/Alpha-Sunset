"""프록시 펀드 N-PORT 보유내역 → data/holdings/*.parquet + manifest.json.

스냅샷: 백테스트 사건별로 사건일 이전에 공개된 가장 최근 공시 + 라이브용 최신 공시.
gfc_2008은 N-PORT 공개 데이터(2019년~)가 없어 제외한다 (plans.md 11장).
사용: python -m scripts.build_holdings
"""

from __future__ import annotations

import json

from app.config import ROOT_DIR
from app.corpus import DATA_DIR, load_events, load_portfolio
from app.data.nport import SecClient, pick_filing

OUT_DIR = DATA_DIR / "holdings"
EXCLUDED_EVENTS = {"gfc_2008"}


def main() -> None:
    portfolio = load_portfolio()
    tickers = sorted({n.proxy_fund.ticker for n in portfolio.nodes if n.proxy_fund})
    snapshots = {e.id: e.date for e in load_events() if e.id not in EXCLUDED_EVENTS}
    snapshots["live"] = None

    sec = SecClient()
    funds = sec.resolve_funds(tickers)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for ticker in tickers:
        fund = funds[ticker]
        filings = sec.list_filings(fund.series_id)
        for snap, before in snapshots.items():
            filing = pick_filing(filings, before)
            if filing is None:
                print(f"{ticker} {snap}: 해당 시점 이전 공시 없음")
                continue
            meta, df = sec.holdings(filing)
            path = OUT_DIR / f"{ticker}_{snap}.parquet"
            df.to_parquet(path, index=False)
            manifest.append({
                "ticker": ticker, "series_id": fund.series_id, "cik": fund.cik, "snapshot": snap,
                "filing_date": filing.filing_date.isoformat(), "rep_pd_date": meta["rep_pd_date"],
                "series_name": meta["series_name"], "net_assets_usd": meta["net_assets_usd"],
                "n_holdings": len(df), "url": filing.folder_url + "primary_doc.xml",
                "file": str(path.relative_to(ROOT_DIR)),
            })
            print(f"{ticker:5s} {snap:14s} 보고기준 {meta['rep_pd_date']} 공시 {filing.filing_date} 종목 {len(df)}")

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 포트폴리오에 N-PORT series_id 기록
    path = DATA_DIR / "portfolio.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for node in data["nodes"]:
        if node.get("proxy_fund"):
            node["proxy_fund"]["nport_series_id"] = funds[node["proxy_fund"]["ticker"]].series_id
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n스냅샷 {len(manifest)}개 저장")


if __name__ == "__main__":
    main()
