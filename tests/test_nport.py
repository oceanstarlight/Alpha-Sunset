from datetime import date

from app.data.nport import Filing, parse_filing_feed, parse_nport, pick_filing

FEED = """<feed><entry><content>
<filing-date>2023-02-28</filing-date>
<filing-href>https://www.sec.gov/Archives/edgar/data/1/0001-23-000002/0001-23-000002-index.htm</filing-href>
</content></entry><entry><content>
<filing-date>2022-11-28</filing-date>
<filing-href>https://www.sec.gov/Archives/edgar/data/1/0001-22-000001/0001-22-000001-index.htm</filing-href>
</content></entry></feed>"""

NPORT = """<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
<formData><genInfo><seriesName>Test ETF</seriesName><seriesId>S000000001</seriesId><repPdDate>2022-12-31</repPdDate></genInfo>
<fundInfo><netAssets>1000.5</netAssets></fundInfo>
<invstOrSecs>
<invstOrSec><name>Bank A</name><lei>L1</lei><title>Bank A Common</title><cusip>111</cusip>
<identifiers><isin value="US111"/></identifiers><valUSD>600</valUSD><pctVal>60.0</pctVal>
<assetCat>EC</assetCat><issuerCat>CORP</issuerCat><invCountry>US</invCountry></invstOrSec>
<invstOrSec><name>Bank B</name><title>Bank B</title><cusip>222</cusip><valUSD>N/A</valUSD><pctVal>40.0</pctVal>
<assetCat>EC</assetCat><issuerCat>CORP</issuerCat><invCountry>KR</invCountry></invstOrSec>
</invstOrSecs></formData></edgarSubmission>"""


def test_parse_feed_and_pick_filing_before_event():
    filings = parse_filing_feed(FEED)
    assert filings[0].folder_url.endswith("/0001-23-000002/")
    assert pick_filing(filings, date(2023, 3, 10)).filing_date == date(2023, 2, 28)
    assert pick_filing(filings, date(2023, 2, 28)).filing_date == date(2022, 11, 28)  # 당일 공시는 제외
    assert pick_filing(filings, date(2022, 1, 1)) is None
    assert pick_filing(filings, None).filing_date == date(2023, 2, 28)


def test_parse_nport_holdings():
    meta, df = parse_nport(NPORT)
    assert meta == {"series_id": "S000000001", "series_name": "Test ETF", "rep_pd_date": "2022-12-31", "net_assets_usd": 1000.5}
    assert df["issuer"].tolist() == ["Bank A", "Bank B"]
    assert df.loc[0, "isin"] == "US111"
    assert df["val_usd"].isna().tolist() == [False, True]
    assert df["country"].tolist() == ["US", "KR"]


def test_committed_snapshots_respect_event_dates():
    import json

    from app.corpus import DATA_DIR, load_events

    manifest = json.loads((DATA_DIR / "holdings" / "manifest.json").read_text(encoding="utf-8"))
    dates = {e.id: e.date for e in load_events()}
    for m in manifest:
        assert m["snapshot"] != "gfc_2008"
        if m["snapshot"] in dates:
            assert date.fromisoformat(m["filing_date"]) < dates[m["snapshot"]]
