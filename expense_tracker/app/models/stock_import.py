"""
券商對帳單匯入 — 從券商匯出的成交明細 CSV 聚合出每支股票的初始倉位。

取股名、成交股數、成本（含手續費）、買賣別、日期，
以時間順序重播（移動平均法）算出每支股票目前的淨股數與加權平均成本，
再據此建立 opening（期初持股）倉位。

券商對帳單通常只有中文股名、沒有股票代碼，但 yfinance 需要代碼查價。
因此匯入時以台灣證交所(TWSE)＋櫃買中心(TPEX)公開清單做 股名→代碼 對照，
自動填入 symbol；對照不到的（或使用者想修正的）會在預覽畫面留成可編輯欄位。
股名本身保持原樣，不做任何清洗（保留 * 等註記）。
"""
import csv
import json
import time
import urllib.request
from datetime import datetime

# TWSE 上市 + TPEX 上櫃公開清單（含股票、ETF），提供 代碼↔名稱 對照。
_LISTING_SOURCES = [
    ("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", "Code", "Name"),
    ("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
     "SecuritiesCompanyCode", "CompanyName"),
]
_NAME_TO_CODE: dict = {}
_LISTING_TS = 0.0
_LISTING_TTL = 24 * 3600  # 清單一天內快取，避免每次匯入都打外部 API


def _load_listing() -> dict:
    """抓取並快取台股 股名→代碼 對照表；抓取失敗時回傳現有（可能為空）快取。"""
    global _NAME_TO_CODE, _LISTING_TS
    if _NAME_TO_CODE and (time.time() - _LISTING_TS) < _LISTING_TTL:
        return _NAME_TO_CODE
    mapping = {}
    for url, code_k, name_k in _LISTING_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            for d in data:
                name = (d.get(name_k) or "").strip()
                code = (d.get(code_k) or "").strip()
                if name and code:
                    mapping.setdefault(name, code)
        except Exception:
            continue
    if mapping:
        _NAME_TO_CODE = mapping
        _LISTING_TS = time.time()
    return _NAME_TO_CODE


def resolve_symbol(name: str) -> str:
    """以股名查代碼；先原樣查，再去掉 * 等註記查。查不到回傳空字串。"""
    listing = _load_listing()
    if not listing:
        return ""
    name = (name or "").strip()
    if name in listing:
        return listing[name]
    stripped = name.rstrip("*＊ ").strip()
    return listing.get(stripped, "")

# 券商 CSV 的欄位名稱（國泰證券對帳單格式）。以「包含」比對，
# 容忍不同券商的細微命名差異。
_COL_HINTS = {
    "name":   ["股名", "商品名稱", "股票名稱", "名稱"],
    "shares": ["成交股數", "股數", "成交數量", "數量"],
    "side":   ["買賣別", "買賣", "交易別"],
    "cost":   ["成本", "價金", "成交金額"],
    "fee":    ["手續費"],
    "date":   ["日期", "成交日期", "交易日期"],
}

_BUY_HINTS = ("買", "buy", "b")
_SELL_HINTS = ("賣", "sell", "s")


def _num(value: str) -> float:
    """券商金額欄含千分位逗號、可能帶引號或空白。"""
    s = str(value).strip().replace(",", "").replace('"', "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_col(header: list, hints: list) -> str | None:
    for col in header:
        low = col.strip().lower()
        if any(h.lower() in low for h in hints):
            return col.strip()
    return None


def _detect_header(rows: list) -> int:
    """券商匯出檔第一行常是「根據您篩選…」的說明列，真正的表頭在其後。
    回傳含有股名/買賣別等關鍵欄位的那一列 index。"""
    for i, row in enumerate(rows[:5]):
        joined = ",".join(row)
        if ("股名" in joined or "股票名稱" in joined or "名稱" in joined) and \
           ("買賣" in joined or "股數" in joined):
            return i
    return 0


def parse_broker_csv(file_path: str) -> dict:
    """
    回傳每支股票的聚合初始倉位：
      {"positions": [{name, symbol, shares, total_cost, avg_price, last_date}], "skipped": int}
    symbol 由 股名→台股清單 自動對應，查不到則為空字串（待使用者於預覽補上）。

    聚合方式（移動平均）：
      現買：shares += 股數；total_cost += (成本 + 手續費)
      現賣：先以當前均價沖銷賣出股數的成本，再扣股數；手續費不影響剩餘成本
    最終只保留 shares > 0 的股票。
    """
    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        all_rows = list(csv.reader(f))
    if not all_rows:
        return {"positions": [], "skipped": 0}

    hdr_idx = _detect_header(all_rows)
    header = [c.strip() for c in all_rows[hdr_idx]]
    data_rows = all_rows[hdr_idx + 1:]

    col_name   = _find_col(header, _COL_HINTS["name"])
    col_shares = _find_col(header, _COL_HINTS["shares"])
    col_side   = _find_col(header, _COL_HINTS["side"])
    col_cost   = _find_col(header, _COL_HINTS["cost"])
    col_fee    = _find_col(header, _COL_HINTS["fee"])
    col_date   = _find_col(header, _COL_HINTS["date"])

    if not (col_name and col_shares and col_side and col_cost):
        raise ValueError("無法辨識券商對帳單欄位（需有股名、成交股數、買賣別、成本）")

    idx = {c: i for i, c in enumerate(header)}

    def cell(row, col):
        i = idx.get(col)
        return row[i].strip() if col and i is not None and i < len(row) else ""

    # 先收集每支股票的交易，依日期排序後重播
    per_stock = {}  # name -> list[(date, side, shares, cost, fee)]
    skipped = 0
    for row in data_rows:
        if not any(c.strip() for c in row):
            continue
        name = cell(row, col_name)
        if not name:
            skipped += 1
            continue
        shares = _num(cell(row, col_shares))
        side_raw = cell(row, col_side).lower()
        cost = _num(cell(row, col_cost))
        fee = _num(cell(row, col_fee)) if col_fee else 0.0
        date = cell(row, col_date) if col_date else ""

        if any(h in side_raw for h in _BUY_HINTS):
            side = "buy"
        elif any(h in side_raw for h in _SELL_HINTS):
            side = "sell"
        else:
            skipped += 1
            continue
        if shares <= 0:
            skipped += 1
            continue
        per_stock.setdefault(name, []).append((date, side, shares, cost, fee))

    positions = []
    for name, txs in per_stock.items():
        txs.sort(key=lambda t: _norm_date(t[0]))
        shares = 0.0
        total_cost = 0.0
        last_date = ""
        for date, side, s, cost, fee in txs:
            if date:
                nd = _norm_date(date)
                if nd > last_date:
                    last_date = nd
            if side == "buy":
                shares += s
                total_cost += cost + fee
            else:  # sell
                if shares > 0:
                    avg = total_cost / shares
                    total_cost -= avg * min(s, shares)
                shares -= s
                if shares <= 0:
                    shares = 0
                    total_cost = 0

        shares = int(round(shares))
        if shares <= 0:
            continue
        avg_price = round(total_cost / shares, 4) if shares > 0 else 0
        positions.append({
            "name": name,
            "symbol": resolve_symbol(name),   # 查得到就自動填，查不到留空待使用者輸入
            "shares": shares,
            "total_cost": round(total_cost, 2),
            "avg_price": avg_price,
            "last_date": last_date or datetime.now().strftime("%Y-%m-%d"),
        })

    positions.sort(key=lambda p: p["total_cost"], reverse=True)
    return {"positions": positions, "skipped": skipped}


def mark_existing_positions(positions: list, existing_stocks: list) -> dict:
    """
    比對聚合出的倉位是否已存在於目前持股（stocks.csv），標記 existing=True/False。
    比對規則與 StockModel.import_opening_positions 的去重邏輯一致：
    有代碼以代碼比對，否則以股名比對。

    回傳 {"positions": [...每筆多了 existing 欄位...], "existing_count": int}。
    """
    existing_symbols = {s.get("symbol") for s in existing_stocks if s.get("symbol")}
    existing_names = {s.get("name") for s in existing_stocks}

    existing_count = 0
    for p in positions:
        symbol = (p.get("symbol") or "").strip().upper()
        name = (p.get("name") or "").strip()
        is_existing = (symbol and symbol in existing_symbols) or \
                      (not symbol and name in existing_names)
        p["existing"] = is_existing
        if is_existing:
            existing_count += 1

    return {"positions": positions, "existing_count": existing_count}


def _norm_date(value: str) -> str:
    """轉為可排序的 YYYY-MM-DD；無法解析則回傳原值。"""
    value = (value or "").strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value
