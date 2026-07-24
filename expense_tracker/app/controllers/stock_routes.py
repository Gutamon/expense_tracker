import os
import re
import tempfile
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, abort
from app.models.stock import StockModel
from app.models.account import AccountModel
from app.models import csv_store
from app.models.stock_import import parse_broker_csv, mark_existing_positions

try:
    import yfinance as yf
    _YF_AVAILABLE = True
    # 查價時常規性地以多個代碼後綴（.TW/.TWO）重試，失敗屬預期行為，
    # 但 yfinance 會把每次失敗都印成 error log，靜音以免洗版終端機/伺服器日誌。
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
except ImportError:
    _YF_AVAILABLE = False

stock_bp = Blueprint("stock", __name__)
stock_model = StockModel()
account_model = AccountModel()

# 台股代碼格式：傳統股票/ETF 是純 4-6 位數字（如 2330），
# 新制主動式 ETF 則是數字+單一英文字母（如 00981A、00988A）。
# 兩者都要嘗試補上 .TW / .TWO 後綴查詢，否則後綴判斷只認純數字會漏掉這些新代碼。
_TW_SYMBOL_RE = re.compile(r"^\d{4,6}[A-Z]?$")


def _tw_price_candidates(symbol: str) -> list:
    if _TW_SYMBOL_RE.match(symbol.replace(".", "")):
        return [symbol + ".TW", symbol + ".TWO", symbol]
    return [symbol]


@stock_bp.route("/stocks")
def manage_stocks():
    stocks = stock_model.get_all()
    accounts = AccountModel().get_all()
    acc_sort = {str(a["id"]): int(a.get("sort_order") or 0) for a in accounts}
    # 自訂順序＝倉位連動帳戶（設定 > 帳戶）的 sort_order；未連動則排最後
    stocks.sort(key=lambda x: (
        int(x.get("shares") or 0) == 0,
        acc_sort.get(str(x.get("linked_account_id")), len(acc_sort)),
    ))
    transactions = stock_model.get_transactions()

    total_cost = 0
    total_value = 0
    for s in stocks:
        total_cost += float(s.get("shares") or 0) * float(s.get("avg_price") or 0)
        total_value += float(s.get("shares") or 0) * float(s.get("current_price") or 0)
    total_pl = total_value - total_cost

    return render_template("stocks.html", stocks=stocks, transactions=transactions,
                           accounts=accounts, total_cost=total_cost,
                           total_value=total_value, total_pl=total_pl, username="")


@stock_bp.route("/api/stocks", methods=["POST"])
def api_create_position():
    data = request.get_json(force=True)
    symbol = data.get("symbol", "").upper().strip()
    name = data.get("name", "").strip()
    account_id = data.get("account_id")
    init_shares = int(data.get("init_shares") or 0)
    init_cost = float(data.get("init_cost") or 0)
    init_date = (data.get("init_date") or "").strip()

    if not symbol or not name or not account_id:
        abort(400, "缺少必要欄位 (代號、名稱、交割帳號)")
    if not re.match(r"^[A-Z0-9.]+$", symbol):
        abort(400, "代號只能包含大寫英文字母、數字與點")
    if init_shares < 0 or init_cost < 0:
        abort(400, "初始股數與總成本不可為負數")
    if init_cost > 0 and init_shares <= 0:
        abort(400, "設定初始總成本時必須填寫初始股數")

    if _YF_AVAILABLE:
        candidates = _tw_price_candidates(symbol)
        found = False
        for candidate in candidates:
            try:
                info = yf.Ticker(candidate).fast_info
                if float(info.last_price or 0) > 0:
                    found = True
                    break
            except Exception:
                continue
        if not found:
            abort(400, f"查無此股票代號：{symbol}")

    new_id = stock_model.create_position(symbol, name, int(account_id))
    if not new_id:
        abort(400, "該股票倉位已存在")

    linked_acc_id = account_model.create(name=name, icon="📈", type="asset",
                                         sub_type="投資", is_asset=1, currency="TWD")
    rows = csv_store.read_csv("stocks.csv")
    for r in rows:
        if str(r.get("id")) == str(new_id):
            r["linked_account_id"] = int(linked_acc_id)
            break
    csv_store.write_csv("stocks.csv", rows, csv_store.SCHEMA["stocks.csv"])

    if init_shares > 0:
        stock_model.add_transaction(
            stock_id=int(new_id),
            t_type="opening",
            date=init_date or date.today().isoformat(),
            shares=init_shares,
            price=round(init_cost / init_shares, 4),
            fee=0,
            note="期初持股",
        )

    return jsonify({"success": True, "id": new_id}), 201


@stock_bp.route("/api/stocks/update-prices", methods=["POST"])
def api_update_all_prices():
    if not _YF_AVAILABLE:
        return jsonify({"error": "yfinance 未安裝，請手動輸入現價"}), 503

    # 只用股票代碼查價；沒有代碼的（例如匯入時未對應到）直接跳過，不嘗試用名稱查詢。
    stocks = [s for s in stock_model.get_all() if s.get("symbol")]
    if not stocks:
        return jsonify({"updated": 0, "failed": []})

    def _fetch_price(symbol):
        for candidate in _tw_price_candidates(symbol):
            try:
                info = yf.Ticker(candidate).fast_info
                price = float(info.last_price or 0)
                if price > 0:
                    return price
            except Exception:
                continue
        return None

    # 每支股票的查價是獨立的網路 I/O，平行處理大幅縮短總等待時間。
    price_by_id = {}
    failed = []
    with ThreadPoolExecutor(max_workers=min(8, len(stocks))) as pool:
        future_to_stock = {pool.submit(_fetch_price, s["symbol"]): s for s in stocks}
        for future in as_completed(future_to_stock):
            s = future_to_stock[future]
            price = future.result()
            if price:
                price_by_id[str(s["id"])] = price
            else:
                failed.append(s["symbol"])

    updated = stock_model.update_prices_bulk(price_by_id)

    return jsonify({"updated": updated, "failed": failed})


@stock_bp.route("/api/stocks/<int:stock_id>/price", methods=["PUT"])
def api_update_stock_price(stock_id):
    data = request.get_json(force=True)
    price = data.get("price")
    if price is None:
        abort(400, "缺少 price")
    if not stock_model.update_price(stock_id, float(price)):
        abort(404, "找不到此倉位")
    return jsonify({"success": True})


@stock_bp.route("/api/stocks/<int:stock_id>/account", methods=["PATCH"])
def api_update_stock_account(stock_id):
    data = request.get_json(force=True)
    account_id = data.get("account_id")
    if not account_id:
        abort(400, "缺少 account_id")
    rows = csv_store.read_csv("stocks.csv")
    for r in rows:
        if str(r.get("id")) == str(stock_id):
            r["account_id"] = int(account_id)
            csv_store.write_csv("stocks.csv", rows, csv_store.SCHEMA["stocks.csv"])
            return jsonify({"success": True})
    abort(404, "找不到此倉位")


@stock_bp.route("/api/stocks/<int:stock_id>/name", methods=["PUT"])
def api_update_stock_name(stock_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        abort(400, "名稱不能為空")
    rows = csv_store.read_csv("stocks.csv")
    for r in rows:
        if str(r.get("id")) == str(stock_id):
            r["name"] = name
            csv_store.write_csv("stocks.csv", rows, csv_store.SCHEMA["stocks.csv"])
            linked = int(r.get("linked_account_id") or 0)
            if linked:
                account_model.update(linked, {"name": name})
            return jsonify({"success": True})
    abort(404, "找不到該倉位")


@stock_bp.route("/api/stocks/transactions", methods=["POST"])
def api_add_transaction():
    data = request.get_json(force=True)
    if not all(k in data for k in ("stock_id", "type", "date")):
        abort(400, "缺少必要欄位")

    t_type = data["type"]
    shares = int(data.get("shares", 0))
    price = float(data.get("price", 0))
    fee = float(data.get("fee", 0))

    if t_type == "split" and price <= 0:
        abort(400, "分割比例必須大於 0")

    new_id = stock_model.add_transaction(
        stock_id=int(data["stock_id"]),
        t_type=t_type,
        date=data["date"],
        shares=shares,
        price=price,
        fee=fee,
        note=data.get("note", ""),
    )
    return jsonify({"success": True, "id": new_id}), 201


@stock_bp.route("/api/stocks/transactions/<int:tx_id>", methods=["PUT"])
def api_update_stock_transaction(tx_id):
    data = request.get_json(force=True)
    try:
        success = stock_model.update_transaction(
            tx_id=tx_id,
            date=data.get("date"),
            shares=data.get("shares", 0),
            price=data.get("price", 0),
            fee=data.get("fee", 0),
            note=data.get("note", ""),
        )
        if not success:
            abort(404, "找不到此明細或更新失敗")
        return jsonify({"success": True})
    except ValueError as e:
        abort(400, str(e))


@stock_bp.route("/api/stocks/<int:stock_id>", methods=["DELETE"])
def api_delete_position(stock_id):
    if not stock_model.delete_position(stock_id):
        abort(400, "此倉位有交易紀錄或找不到，無法刪除")
    return jsonify({"success": True})


@stock_bp.route("/api/stocks/transactions/<int:tx_id>", methods=["DELETE"])
def api_delete_stock_transaction(tx_id):
    try:
        if stock_model.delete_transaction(tx_id):
            return jsonify({"success": True})
        abort(404, "找不到此明細或刪除失敗")
    except ValueError as e:
        abort(400, str(e))


@stock_bp.route("/api/stocks/import/preview", methods=["POST"])
def api_stocks_import_preview():
    """
    解析上傳的券商對帳單，回傳每支股票聚合後的初始倉位（不寫入）。
    overwrite=true 時（表單欄位，字串 "true"）代表使用者打算用這份對帳單覆蓋所有
    現有股票資料，此時預覽不與現有持股/交易比對去重——反正比對基準即將被清空，
    對帳單裡的每支股票都當作全新倉位處理。
    """
    f = request.files.get("file")
    if not f:
        abort(400, "請上傳券商對帳單 CSV")
    if not f.filename.lower().endswith(".csv"):
        abort(400, "僅支援 CSV 格式")
    overwrite = (request.form.get("overwrite") or "").lower() == "true"

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".csv")
    try:
        os.close(tmp_fd)
        f.save(tmp_path)
        result = parse_broker_csv(tmp_path)
        if overwrite:
            for p in result["positions"]:
                p["existing"] = False
            result["existing_count"] = 0
        else:
            existing_stocks = stock_model.get_all()
            existing_txs = stock_model.get_transactions()
            mark_result = mark_existing_positions(result["positions"], existing_stocks, existing_txs)
            result["positions"] = mark_result["positions"]
            result["existing_count"] = mark_result["existing_count"]
    except ValueError as e:
        abort(400, str(e))
    except Exception as e:
        abort(500, str(e))
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return jsonify(result)


@stock_bp.route("/api/stocks/import", methods=["POST"])
def api_stocks_import():
    """
    依使用者確認的倉位清單批次建立期初倉位。
    overwrite=true 時，會先清空所有股票倉位、交易紀錄與連動投資帳戶
    （StockModel.reset_all），再重新匯入這份對帳單——用於「這份 CSV 才是完整
    真實紀錄，之前建立的都作廢」的情境。這是破壞性操作，不可復原。
    """
    data = request.get_json(force=True)
    account_id = data.get("account_id")
    positions = data.get("positions", [])
    overwrite = bool(data.get("overwrite"))
    if not account_id:
        abort(400, "請選擇交割帳號")
    if not positions:
        abort(400, "沒有可匯入的倉位")
    reset_count = stock_model.reset_all() if overwrite else 0
    result = stock_model.import_opening_positions(positions, int(account_id))
    return jsonify({"success": True, "reset_count": reset_count, **result})


def _historical_close(symbol: str, end_date: str):
    """查 symbol 於 end_date 當天（或之前最近一個交易日）的收盤價。查不到回傳 None。"""
    candidates = _tw_price_candidates(symbol)
    end = datetime.strptime(end_date, "%Y-%m-%d")
    start = end - timedelta(days=10)
    fetch_end = end + timedelta(days=1)  # yfinance end 為 exclusive
    for candidate in candidates:
        try:
            hist = yf.Ticker(candidate).history(
                start=start.strftime("%Y-%m-%d"), end=fetch_end.strftime("%Y-%m-%d"))
            if hist.empty:
                continue
            price = float(hist["Close"].iloc[-1])
            if price > 0:
                return price
        except Exception:
            continue
    return None


@stock_bp.route("/api/stocks/holdings-as-of", methods=["POST"])
def api_stocks_holdings_as_of():
    """
    報酬分析用：依 end_date 重建所有股票（含目前已平倉、尚未出現在主頁的）的持股狀態，
    只回傳當時仍持有（shares > 0）的股票清單，供勾選清單即時依日期篩選。
    純重播 stock_transactions，不查即時/歷史股價，速度快。
    """
    data = request.get_json(force=True)
    end_date = (data.get("end_date") or "").strip()
    if not end_date:
        abort(400, "缺少結束日期")
    try:
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        abort(400, "結束日期格式錯誤")

    items = []
    for s in stock_model.get_all():
        holding = stock_model.holding_as_of(int(s["id"]), end_date)
        if holding["shares"] > 0:
            items.append({
                "id": s["id"], "symbol": s.get("symbol"), "name": s.get("name"),
                "shares": holding["shares"], "avg_price": holding["avg_price"],
            })
    items.sort(key=lambda x: x["name"])
    return jsonify({"items": items})


@stock_bp.route("/api/stocks/performance", methods=["POST"])
def api_stocks_performance():
    """
    區間績效：計算所選股票於 end_date 當下的總報酬率。
    股數/成本不是直接讀 stocks.csv 目前的 shares/avg_price，而是重播該股票
    在 end_date（含）以前的交易（StockModel.holding_as_of）算出「end_date 當下」
    的持股狀態——避免把 end_date 之後才買入、或 end_date 之前已平倉的股票，
    誤用目前的股數/均價算入。end_date 當下股數為 0（尚未買進或已平倉）的股票
    直接排除在外。
    總成本 = Σ(end_date 當下持有成本)；結束總市值 = Σ(end_date 當下股數 × 收盤價)。
    end_date 為今天（或更晚）時股價直接用目前現價，不查歷史股價。
    """
    if not _YF_AVAILABLE:
        return jsonify({"error": "yfinance 未安裝，無法查詢歷史股價"}), 503

    data = request.get_json(force=True)
    end_date = (data.get("end_date") or "").strip()
    stock_ids = {str(i) for i in (data.get("stock_ids") or [])}
    if not end_date:
        abort(400, "缺少結束日期")
    if not stock_ids:
        abort(400, "請至少勾選一支股票")

    try:
        datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        abort(400, "結束日期格式錯誤")

    is_today_or_future = end_date >= date.today().isoformat()

    all_stocks = {str(s["id"]): s for s in stock_model.get_all()}
    holdings = []  # (stock, holding) pairs，僅保留 end_date 當下股數 > 0 的
    excluded = 0
    for sid in stock_ids:
        s = all_stocks.get(sid)
        if not s:
            continue
        holding = stock_model.holding_as_of(int(sid), end_date)
        if holding["shares"] <= 0:
            excluded += 1
            continue
        holdings.append((s, holding))
    if not holdings:
        abort(400, "所選股票於結束日期當下皆無持股（尚未買進或已平倉）")

    def _end_price(s):
        if is_today_or_future:
            return float(s.get("current_price") or 0)
        if not s.get("symbol"):
            return None
        return _historical_close(s["symbol"], end_date)

    items = []
    failed = []
    with ThreadPoolExecutor(max_workers=min(8, len(holdings))) as pool:
        future_to_pair = {pool.submit(_end_price, s): (s, h) for s, h in holdings}
        for future in as_completed(future_to_pair):
            s, holding = future_to_pair[future]
            price = future.result()
            shares = holding["shares"]
            cost = holding["cost"]
            if price is None:
                failed.append(s.get("symbol") or s.get("name"))
                value = cost  # 查無股價時以成本頂替，避免整體報酬率失真為缺漏
                price = holding["avg_price"]
            else:
                value = shares * price
            items.append({
                "id": s["id"], "symbol": s.get("symbol"), "name": s.get("name"),
                "shares": shares, "avg_price": holding["avg_price"], "end_price": round(price, 4),
                "cost": round(cost, 2), "value": round(value, 2),
            })

    items.sort(key=lambda x: x["value"], reverse=True)
    total_cost = sum(i["cost"] for i in items)
    total_value = sum(i["value"] for i in items)
    total_pl = total_value - total_cost
    total_pct = (total_pl / total_cost * 100) if total_cost > 0 else 0

    return jsonify({
        "items": items,
        "failed": failed,
        "excluded": excluded,
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pl": round(total_pl, 2),
        "total_pct": round(total_pct, 2),
    })
