import re
from flask import Blueprint, render_template, request, jsonify, abort
from app.models.stock import StockModel
from app.models.account import AccountModel
from app.models import csv_store

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

stock_bp = Blueprint("stock", __name__)
stock_model = StockModel()
account_model = AccountModel()


@stock_bp.route("/stocks")
def manage_stocks():
    stocks = stock_model.get_all()
    stocks.sort(key=lambda x: (int(x.get("shares") or 0) == 0, -int(x.get("id") or 0)))
    transactions = stock_model.get_transactions()
    accounts = AccountModel().get_all()

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

    if not symbol or not name or not account_id:
        abort(400, "缺少必要欄位 (代號、名稱、交割帳號)")
    if not re.match(r"^[A-Z0-9.]+$", symbol):
        abort(400, "代號只能包含大寫英文字母、數字與點")

    if _YF_AVAILABLE:
        candidates = ([symbol + ".TW", symbol + ".TWO", symbol]
                      if symbol.replace(".", "").isdigit() else [symbol])
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

    return jsonify({"success": True, "id": new_id}), 201


@stock_bp.route("/api/stocks/update-prices", methods=["POST"])
def api_update_all_prices():
    if not _YF_AVAILABLE:
        return jsonify({"error": "yfinance 未安裝，請手動輸入現價"}), 503

    stocks = stock_model.get_all()
    if not stocks:
        return jsonify({"updated": 0, "failed": []})

    def _fetch_price(symbol):
        """Try symbol as-is; for pure-digit TW symbols also try .TW / .TWO suffixes."""
        candidates = [symbol]
        if symbol.replace(".", "").isdigit():
            candidates = [symbol + ".TW", symbol + ".TWO", symbol]
        for candidate in candidates:
            try:
                info = yf.Ticker(candidate).fast_info
                price = float(info.last_price or 0)
                if price > 0:
                    return price
            except Exception:
                continue
        return None

    updated = 0
    failed = []
    for s in stocks:
        symbol = s.get("symbol", "")
        if not symbol:
            continue
        price = _fetch_price(symbol)
        if price:
            stock_model.update_price(s["id"], price)
            updated += 1
        else:
            failed.append(symbol)

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
