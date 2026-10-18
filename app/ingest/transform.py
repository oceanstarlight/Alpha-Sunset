"""매핑 규칙을 전체 행에 적용하고 검증한다. 모든 단계는 원인-근거-결과로 남긴다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from app.config import ROOT_DIR
from app.ingest.mapper import MappingSpec
from app.ingest.profile import ISIN_RE, SheetProfile, to_number
from app.ingest.reader import Sheet
from app.ingest.schema import Holding

PRESET_DIR = ROOT_DIR / "data" / "ingest" / "presets"

KO_COUNTRY = {"한국": "KR", "대한민국": "KR", "국내": "KR", "미국": "US", "중국": "CN", "일본": "JP", "영국": "GB", "독일": "DE",
              "프랑스": "FR", "홍콩": "HK", "대만": "TW", "인도": "IN", "베트남": "VN", "캐나다": "CA", "호주": "AU", "스위스": "CH",
              "네덜란드": "NL", "싱가포르": "SG", "브라질": "BR", "멕시코": "MX", "인도네시아": "ID", "아일랜드": "IE",
              "룩셈부르크": "LU", "케이맨": "KY", "케이맨제도": "KY", "스웨덴": "SE", "덴마크": "DK", "스페인": "ES", "이탈리아": "IT"}
EN_COUNTRY_EXTRA = {"Korea (South)": "KR", "Korea": "KR", "Republic of Korea": "KR", "United States of America": "US",
                    "USA": "US", "UK": "GB", "Cayman Islands": "KY", "European Union": "EU"}
ASSET_WORDS = [  # (키워드, 자산군) — 앞에서부터 먼저 일치하는 것
    (("선물", "옵션", "스왑", "futures", "future", "option", "swap", "forward", "derivative"), "derivatives"),
    (("국채", "국고채", "treasury", "government", "sovereign", "통안"), "govt_bond"),
    (("회사채", "사채", "corporate", "credit", "bond", "채권"), "corporate_bond"),
    (("현금", "예금", "cash", "mmf", "money market", "콜론", "rp"), "money_market"),
    (("부동산", "리츠", "reit", "real estate"), "real_estate"),
    (("원자재", "금", "commodity", "gold"), "commodity"),
    (("etf", "펀드", "수익증권", "fund"), "fund"),
    (("주식", "보통주", "우선주", "equity", "stock", "share"), "equity"),
]


@dataclass
class IngestResult:
    holdings: pd.DataFrame
    chain: list[dict[str, str]]
    dropped: list[dict] = field(default_factory=list)  # {row, reason}
    spec: MappingSpec | None = None


def isin_valid(code: str) -> bool:
    """ISO 6166 검증 숫자 (Luhn)."""
    if not ISIN_RE.match(code or ""):
        return False
    digits = "".join(str(int(ch, 36)) for ch in code[:-1])
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 0:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return (10 - total % 10) % 10 == int(code[-1])


def norm_country(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s or s in ("-", "nan"):
        return None
    if len(s) == 2 and s.isascii() and s.isalpha():
        return s.upper()
    if s in KO_COUNTRY:
        return KO_COUNTRY[s]
    if s in EN_COUNTRY_EXTRA:
        return EN_COUNTRY_EXTRA[s]
    from app import geo

    return geo.code_for_name(s)


def norm_asset(v) -> str:
    s = str(v or "").strip().lower()
    for words, cls in ASSET_WORDS:
        if any(w in s for w in words):
            return cls
    return "other"


HOLDING_WORDS = [(("거래상대방", "counterparty", "cp"), "counterparty"), (("위탁", "외부", "manager", "external", "외부위탁"), "manager"),
                 (("직접", "자가", "direct", "internal", "내부"), "direct")]


def norm_holding_type(v) -> str:
    s = str(v or "").strip().lower()
    for words, t in HOLDING_WORDS:
        if any(w in s for w in words):
            return t
    return "direct"


def apply_spec(sheet: Sheet, profile: SheetProfile, spec: MappingSpec) -> IngestResult:
    h = spec.header_row - 1
    headers = [str(v).strip() if v is not None else "" for v in sheet.rows[h]]
    idx = {name: i for i, name in enumerate(headers)}
    skip = [w.lower() for w in spec.skip_if_contains]
    recs, dropped = [], []
    width = len([x for x in headers if x])
    misaligned = 0
    for r_no, row in enumerate(sheet.rows[h + 1:], start=h + 2):
        if not any(v not in (None, "") for v in row):
            continue
        first = " ".join(str(v) for v in row[:3] if v is not None).strip().lower()
        if any(w and (first == w or first.startswith(w + " ") or first.endswith(" " + w)) for w in skip):
            dropped.append({"row": r_no, "reason": f"합계·소계 행 ('{first[:20]}')"})
            continue
        if len([v for v in row if v not in (None, "")]) and len(row) < width:
            misaligned += 1
        rec: dict = {"source_row": r_no}
        for cm in spec.columns:
            j = idx.get(cm.source)
            v = row[j] if j is not None and j < len(row) else None
            if cm.field == "amount":
                x = to_number(v)
                rec["amount"] = None if x is None else x * cm.multiplier
            elif cm.field == "weight":
                x = to_number(v)
                rec["weight"] = None if x is None else (x / 100 if cm.percent else x)
            else:
                rec[cm.field] = None if v in (None, "", "-") else str(v).strip()
        if not rec.get("name") and not rec.get("isin") and not rec.get("local_code") and not rec.get("ticker"):
            dropped.append({"row": r_no, "reason": "종목명·식별자 없음 (빈 행·주석 추정)"})
            continue
        for k, v in spec.defaults.items():
            rec.setdefault(k, v)
        recs.append(rec)

    df = pd.DataFrame(recs)
    chain = [{"단계": "매핑 규칙", "원인": f"방식 {spec.method}, 헤더 {spec.header_row}행, 열 {len(spec.columns)}개 연결",
              "근거": "; ".join(f"{c.field}←'{c.source}'" + (f" ×{c.multiplier:g}" if c.multiplier != 1 else "")
                              + (" ÷100" if c.percent else "") + f" ({c.reason})" for c in spec.columns)
                      + ("; 기본값: " + ", ".join(f"{k}={v} ({spec.default_reasons.get(k, '')})" for k, v in spec.defaults.items()) if spec.defaults else ""),
              "결과": f"데이터 {len(df)}행 변환, {len(dropped)}행 제외"}]
    if df.empty:
        chain.append({"단계": "변환", "원인": "변환된 행 없음", "근거": "헤더·매핑 확인 필요", "결과": "실패"})
        return IngestResult(df, chain, dropped, spec)

    # 식별자: 값 형식으로 나눠 담는다 (ISIN·국내 코드가 한 열에 섞인 단말 내보내기 대응)
    from app.ingest.profile import KR_CODE_RE
    for col in [c for c in ("isin", "local_code", "ticker") if c in df]:
        vals = df[col].astype(str)
        is_isin = vals.str.match(ISIN_RE.pattern) & df[col].notna()
        is_kr = vals.str.match(KR_CODE_RE.pattern) & df[col].notna()
        if col != "isin" and is_isin.any():
            df.loc[is_isin, "isin"] = vals[is_isin]
        if col != "local_code" and is_kr.any():
            df.loc[is_kr, "local_code"] = vals[is_kr]
        if col in ("isin", "local_code"):
            wrong = ~(is_isin if col == "isin" else is_kr) & df[col].notna()
            if col == "isin":
                df.loc[is_kr, col] = None
            elif wrong.any():
                df.loc[wrong, col] = None
    # 정규화
    if "name" not in df:
        df["name"] = df.get("isin", df.get("local_code", df.get("ticker")))
    if "local_code" in df:
        df["local_code"] = df["local_code"].astype(str).str.replace(r"^A", "", regex=True).str.zfill(6).where(df["local_code"].notna())
    df["asset_class"] = df["asset_class"].map(norm_asset) if "asset_class" in df else "other"
    if "holding_type" in df:
        df["holding_type"] = df["holding_type"].map(norm_holding_type)
    if "country" in df:
        raw_country = df["country"].copy()
        df["country"] = df["country"].map(norm_country)
        unknown = sorted({str(x) for x, c in zip(raw_country, df["country"]) if c is None and x is not None})[:5]
    else:
        df["country"], unknown = None, []
    inferred = 0
    if "isin" in df:
        miss = df["country"].isna() & df["isin"].map(lambda x: isinstance(x, str) and isin_valid(x))
        df.loc[miss, "country"] = df.loc[miss, "isin"].str[:2]
        inferred += int(miss.sum())
    if "local_code" in df:
        miss = df["country"].isna() & df["local_code"].notna()
        df.loc[miss, "country"] = "KR"
        inferred += int(miss.sum())

    # 비중: 없으면 금액으로 계산
    weight_src = "원본 비중 열"
    if ("weight" not in df or df["weight"].isna().all()) and "amount" in df and df["amount"].notna().any():
        total = df["amount"].sum()
        df["weight"] = df["amount"] / total if total else None
        weight_src = "평가금액 / 합계로 계산"
    chain.append({"단계": "정규화",
                  "원인": f"국가 {df['country'].notna().sum()}/{len(df)}행 확정, 자산군 {df['asset_class'].ne('other').sum()}/{len(df)}행 분류",
                  "근거": f"국가: 원본 열 → ISO 코드, 없으면 ISIN 앞 2자리·국내 코드로 추정 {inferred}행"
                          + (f", 인식 못한 국가명 {unknown}" if unknown else "") + f"; 비중: {weight_src}",
                  "결과": "완료" if df["country"].notna().all() else "일부 국가 미상 (노출 분석에서 GLOBAL로 처리)"})

    # 검증
    checks = []
    if "weight" in df and df["weight"].notna().any():
        ws = float(df["weight"].sum())
        checks.append(("비중 합계", f"{ws:.4f}", abs(ws - 1) <= 0.02))
    if "isin" in df:
        bad = [c for c in df["isin"].dropna() if not isin_valid(c)]
        checks.append(("ISIN 검증 숫자", f"오류 {len(bad)}건" + (f" (예: {bad[:3]})" if bad else ""), not bad))
        dup = df["isin"].dropna().duplicated().sum()
        checks.append(("ISIN 중복", f"{dup}건", dup == 0))
    if "amount" in df:
        neg = int((df["amount"] < 0).sum())
        checks.append(("음수 금액(파생·공매도)", f"{neg}건", True))
        checks.append(("금액 합계", f"{df['amount'].sum():,.0f} {df.get('currency', pd.Series(['?'])).iloc[0] if 'currency' in df else ''}", True))
    checks.append(("열 개수가 헤더보다 적은 행", f"{misaligned}건", misaligned == 0))
    if "amount" not in df or df["amount"].isna().all():
        checks.append(("평가금액 열", "찾지 못함 (비중만으로 분석)", False))
    chain.append({"단계": "검증", "원인": "; ".join(f"{n}: {v}" for n, v, _ in checks),
                  "근거": "비중 합계 1±0.02, ISIN은 ISO 6166 검증 숫자(Luhn), 중복·음수 확인",
                  "결과": "통과" if all(ok for _, _, ok in checks) else "확인 필요: " + ", ".join(n for n, _, ok in checks if not ok)})
    for col in ("isin", "ticker", "local_code", "amount", "currency", "weight", "sector", "holding_type", "manager"):
        if col not in df:
            df[col] = None
    df = df[["name", "isin", "ticker", "local_code", "amount", "currency", "weight", "asset_class", "country", "sector",
             "holding_type", "manager", "source_row"]]
    return IngestResult(df, chain, dropped, spec)


def to_holdings(df: pd.DataFrame) -> list[Holding]:
    return [Holding(**{k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in r.items()}) for r in df.to_dict("records")]


# ---------- 양식 저장 (같은 양식은 다음부터 LLM 없이) ----------


def preset_key(profile: SheetProfile) -> str:
    return hashlib.sha1(profile.signature.encode()).hexdigest()[:12]


def save_preset(profile: SheetProfile, spec: MappingSpec, label: str = "") -> Path:
    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    path = PRESET_DIR / f"{preset_key(profile)}.json"
    path.write_text(json.dumps({"label": label, "signature": profile.signature, "spec": spec.model_dump()},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_preset(profile: SheetProfile) -> MappingSpec | None:
    path = PRESET_DIR / f"{preset_key(profile)}.json"
    if not path.exists():
        return None
    spec = MappingSpec.model_validate(json.loads(path.read_text(encoding="utf-8"))["spec"])
    spec.method = "preset"
    return spec


# ---------- 포트폴리오로 변환 (Exposure 입력) ----------


def to_portfolio(df: pd.DataFrame, institution: str = "업로드 포트폴리오", max_nodes: int = 40):
    """국가·자산군·섹터별로 묶어 직접 보유 노드로 만든다 (비중 합 1로 정규화)."""
    from app.schemas import Portfolio, PortfolioNode

    d = df[df["holding_type"].fillna("direct") != "counterparty"].copy()
    d["weight"] = d["weight"].fillna(0).clip(lower=0)
    d["country"] = d["country"].fillna("GLOBAL")
    d["sector"] = d["sector"].fillna("")
    g = d.groupby(["country", "asset_class", "sector"], dropna=False).agg(weight=("weight", "sum"), n=("name", "size"),
                                                                         top=("name", "first")).reset_index()
    g = g.sort_values("weight", ascending=False)
    head, tail = g.head(max_nodes - 1), g.iloc[max_nodes - 1:]
    total = float(g["weight"].sum()) or 1.0
    nodes = []
    for i, r in enumerate(head.itertuples(), start=1):
        nodes.append(PortfolioNode(id=f"U-{i:03d}", name=f"{r.country} {r.asset_class} {r.sector}".strip() + f" ({r.n}종목, 예: {r.top})",
                                   kind="direct", instrument=r.asset_class, weight=r.weight / total, uncertainty=0.0,
                                   regions=[r.country], sectors=[r.sector.lower()] if r.sector else [], asset_classes=[r.asset_class]))
    if len(tail):
        nodes.append(PortfolioNode(id="U-ETC", name=f"기타 {int(tail['n'].sum())}종목", kind="direct", instrument="mixed",
                                   weight=float(tail["weight"].sum()) / total, uncertainty=0.0, regions=["GLOBAL"]))
    # 반올림 오차 보정
    diff = 1.0 - sum(n.weight for n in nodes)
    nodes[0] = nodes[0].model_copy(update={"weight": nodes[0].weight + diff})
    return Portfolio(institution=institution, as_of=date.today(), base_currency=str(df["currency"].dropna().iloc[0]) if df["currency"].notna().any() else "KRW",
                     synthetic=False, nodes=nodes)
