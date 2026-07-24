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
    """
    以股名查代碼。券商對帳單常用自家簡稱，與證交所/櫃買正式名稱不完全一致
    （例如「永豐台灣ESG50」實際正式名稱只是「永豐台灣ESG」，多了數字後綴），
    因此比對順序為：
      1. 完全比對
      2. 去掉 * 等註記後比對
      3. 前綴比對——正式名稱是輸入名稱的前綴，且長度差在容許範圍內
         （檔名/註記差異，而非撞名到別支股票）
    查不到回傳空字串。
    """
    listing = _load_listing()
    if not listing:
        return ""
    name = (name or "").strip()
    if name in listing:
        return listing[name]
    stripped = name.rstrip("*＊ ").strip()
    if stripped in listing:
        return listing[stripped]

    # 前綴比對：只在「正式名稱是輸入名稱的前綴」且差異不大時採用，
    # 避免「永豐」誤配到「永豐金」這種完全不同標的的股票。
    candidates = [n for n in listing if stripped.startswith(n) and len(stripped) - len(n) <= 4]
    if candidates:
        best = max(candidates, key=len)  # 取最長、最貼近的正式名稱
        return listing[best]
    return ""

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


_CSV_ENCODINGS = ("utf-8-sig", "cp950", "big5")


def _read_csv_rows(file_path: str) -> list:
    """
    自動偵測編碼讀取券商 CSV。多數券商系統預設輸出 Big5/CP950，
    若強制用 utf-8-sig 解碼會讓中文股名整批變成替換字元（U+FFFD）而完全查無代碼
    ——不會拋例外、也看不出任何錯誤，只會在對帳結果裡「莫名其妙查不到代碼」。
    因此依序嘗試每種編碼，選第一個「不含替換字元」的結果；全部都有替換字元則
    取替換字元最少的那個，避免無聲吞掉整批中文。
    """
    with open(file_path, "rb") as f:
        raw = f.read()
    best_rows, best_bad_count = None, None
    for enc in _CSV_ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        bad_count = text.count("�")
        if bad_count == 0:
            return list(csv.reader(text.splitlines()))
        if best_bad_count is None or bad_count < best_bad_count:
            best_rows = list(csv.reader(text.splitlines()))
            best_bad_count = bad_count
    return best_rows or []


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
    all_rows = _read_csv_rows(file_path)
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
        tx_list = []
        for date, side, s, cost, fee in txs:
            nd = _norm_date(date) if date else datetime.now().strftime("%Y-%m-%d")
            if nd > last_date:
                last_date = nd
            price = round((cost / s), 4) if s else 0
            tx_list.append({"date": nd, "side": side, "shares": s, "price": price, "fee": fee})
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
        avg_price = round(total_cost / shares, 4) if shares > 0 else 0
        positions.append({
            "name": name,
            "symbol": resolve_symbol(name),   # 查得到就自動填，查不到留空待使用者輸入
            "shares": shares,   # 0 代表對帳單範圍內已完全平倉，仍保留完整交易供匯入
            "total_cost": round(total_cost, 2),
            "avg_price": avg_price,
            "last_date": last_date or datetime.now().strftime("%Y-%m-%d"),
            "txs": tx_list,   # 逐筆交易明細，供匯入時完整寫入 stock_transactions
            "closed": shares <= 0,
        })

    positions.sort(key=lambda p: p["total_cost"], reverse=True)
    return {"positions": positions, "skipped": skipped}


def _tx_fingerprint(date: str, side: str, shares, price, fee) -> tuple:
    """交易去重指紋：對帳單沒有唯一 ID，以 日期+買賣別+股數+單價+手續費 判斷是否為同一筆。"""
    def r(v):
        try:
            return round(float(v or 0), 4)
        except (TypeError, ValueError):
            return 0.0
    return (_norm_date(date), side, r(shares), r(price), r(fee))


def mark_existing_positions(positions: list, existing_stocks: list, existing_txs: list = None) -> dict:
    """
    比對聚合出的倉位是否已存在於目前持股（stocks.csv），標記 existing=True/False。
    比對規則與 StockModel.import_opening_positions 的去重邏輯一致：
    有代碼以代碼比對，否則以股名比對。

    對已存在的股票，進一步比對對帳單裡的逐筆交易（p["txs"]）是否已記錄於
    stock_transactions（existing_txs），把尚未記錄過的交易篩到 p["new_txs"]，
    並附上 p["stock_id"]（供匯入時定位要補寫的股票）。
    去重以 日期+買賣別+股數+單價+手續費 的指紋比對，重複的視為已匯入過。

    回傳 {"positions": [...每筆多了 existing / new_txs / stock_id 欄位...], "existing_count": int}。
    """
    existing_symbols = {s.get("symbol"): s for s in existing_stocks if s.get("symbol")}
    existing_names = {s.get("name"): s for s in existing_stocks}

    tx_fingerprints_by_stock = {}
    for t in (existing_txs or []):
        sid = str(t.get("stock_id"))
        fp = _tx_fingerprint(t.get("date"), t.get("type"), t.get("shares"), t.get("price"), t.get("fee"))
        tx_fingerprints_by_stock.setdefault(sid, set()).add(fp)

    existing_count = 0
    for p in positions:
        symbol = (p.get("symbol") or "").strip().upper()
        name = (p.get("name") or "").strip()
        stock = (symbol and existing_symbols.get(symbol)) or (not symbol and existing_names.get(name))
        is_existing = bool(stock)
        p["existing"] = is_existing
        if is_existing:
            existing_count += 1
            stock_id = str(stock.get("id"))
            p["stock_id"] = stock.get("id")
            seen = tx_fingerprints_by_stock.get(stock_id, set())
            new_txs = []
            for t in (p.get("txs") or []):
                fp = _tx_fingerprint(t.get("date"), t.get("side"), t.get("shares"), t.get("price"), t.get("fee"))
                if fp not in seen:
                    new_txs.append(t)
            p["new_txs"] = new_txs

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
