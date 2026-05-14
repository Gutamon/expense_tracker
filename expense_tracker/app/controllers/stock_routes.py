import re
from datetime import datetime
import yfinance as yf
from flask import Blueprint, render_template, request, jsonify, session, abort, redirect
from app.models.stock import StockModel
from app.models.account import AccountModel
from app.models.db import get_db

stock_bp = Blueprint("stock", __name__)
stock_model = StockModel()

@stock_bp.before_request
def require_login():
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({"error": "未登入"}), 401
        return redirect('/login')

@stock_bp.route("/stocks")
def manage_stocks():
    user_id = session['user_id']
    stocks = stock_model.get_by_user(user_id)
    stocks.sort(key=lambda x: (x['shares'] == 0, -x['id']))
    transactions = stock_model.get_transactions(user_id)
    accounts = AccountModel().get_by_user(user_id)

    total_cost = 0
    total_value = 0
    for s in stocks:
        total_cost += s['shares'] * s['avg_price']
        total_value += s['shares'] * s['current_price']
    total_pl = total_value - total_cost

    return render_template("stocks.html", stocks=stocks, transactions=transactions, accounts=accounts,
                           total_cost=total_cost, total_value=total_value, total_pl=total_pl, username=session.get('username'))

@stock_bp.route("/api/stocks", methods=["POST"])
def api_create_position():
    data = request.get_json(force=True)
    symbol = data.get("symbol", "").upper().strip()
    name = data.get("name", "").strip()
    account_id = data.get("account_id")

    if not symbol or not name or not account_id:
        abort(400, "缺少必要欄位 (代號、名稱、交割帳號)")

    if not re.match(r"^[A-Z0-9]+$", symbol):
        abort(400, "代號只能包含大寫英文字母與數字")

    yf_sym = f"{symbol}.TW" if (symbol.isdigit() or re.match(r'^\d{5}', symbol)) else symbol
    try:
        t = yf.Ticker(yf_sym)
        price = t.info.get("regularMarketPrice") or t.info.get("currentPrice") or t.info.get("previousClose")
        if price is None:
            abort(400, "查無此股票代號 (yfinance 找不到報價)")
    except:
        abort(400, "查無此股票代號 (驗證失敗)")

    new_id = stock_model.create_position(session['user_id'], symbol, name, int(account_id))
    if not new_id:
        abort(400, "該股票倉位已存在")

    with get_db() as conn:
        conn.execute("UPDATE stocks SET current_price = ?, updated_at = ? WHERE id = ?",
                     (float(price), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), new_id))

    return jsonify({"success": True, "id": new_id}), 201

@stock_bp.route("/api/stocks/<int:stock_id>/name", methods=["PUT"])
def api_update_stock_name(stock_id):
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        abort(400, "名稱不能為空")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE stocks SET name = ? WHERE id = ? AND user_id = ?", (name, stock_id, session['user_id']))
        if cursor.rowcount == 0:
            abort(404, "找不到該倉位")

    return jsonify({"success": True})

@stock_bp.route("/api/stocks/info/<symbol>")
def api_stock_info(symbol):
    symbol = symbol.upper().strip()
    yf_sym = f"{symbol}.TW" if (symbol.isdigit() or re.match(r'^\d{5}', symbol)) else symbol
    try:
        t = yf.Ticker(yf_sym)
        info = t.info
        name = info.get("shortName") or info.get("longName") or ""
        return jsonify({"name": name})
    except:
        return jsonify({"name": ""})

@stock_bp.route("/api/stocks/transactions", methods=["POST"])
def api_add_transaction():
    data = request.get_json(force=True)
    required = ("stock_id", "type", "date")
    if not all(k in data for k in required): abort(400, "缺少必要欄位")

    t_type = data["type"]
    shares = int(data.get("shares", 0))
    price = float(data.get("price", 0))
    fee = float(data.get("fee", 0))

    if t_type == "split":
        if price <= 0: abort(400, "分割比例必須大於 0")

    new_id = stock_model.add_transaction(
        user_id=session['user_id'],
        stock_id=int(data["stock_id"]),
        t_type=t_type,
        date=data["date"],
        shares=shares,
        price=price,
        fee=fee,
        note=data.get("note", "")
    )
    return jsonify({"success": True, "id": new_id}), 201

@stock_bp.route("/api/stocks/update_prices", methods=["POST"])
def api_update_prices():
    success = stock_model.update_prices(session['user_id'])
    return jsonify({"success": success})

@stock_bp.route("/api/stocks/transactions/<int:tx_id>", methods=["PUT"])
def api_update_stock_transaction(tx_id):
    data = request.get_json(force=True)
    try:
        success = stock_model.update_transaction(
            user_id=session['user_id'],
            tx_id=tx_id,
            date=data.get("date"),
            shares=data.get("shares", 0),
            price=data.get("price", 0),
            fee=data.get("fee", 0),
            note=data.get("note", "")
        )
        if not success:
            abort(404, "找不到此明細或更新失敗")
        return jsonify({"success": True})
    except ValueError as e:
        abort(400, str(e))

@stock_bp.route("/api/stocks/<int:stock_id>", methods=["DELETE"])
def api_delete_position(stock_id):
    user_id = session['user_id']
    with get_db() as conn:
        cursor = conn.cursor()
        stock = cursor.execute("SELECT id FROM stocks WHERE id = ? AND user_id = ?", (stock_id, user_id)).fetchone()
        if not stock:
            abort(404, "找不到此倉位")
        tx_count = cursor.execute("SELECT COUNT(*) as c FROM stock_transactions WHERE stock_id = ? AND user_id = ?", (stock_id, user_id)).fetchone()['c']
        if tx_count > 0:
            abort(400, "此倉位有交易紀錄，無法直接刪除")
        cursor.execute("DELETE FROM stocks WHERE id = ? AND user_id = ?", (stock_id, user_id))
    return jsonify({"success": True})

@stock_bp.route("/api/stocks/transactions/<int:tx_id>", methods=["DELETE"])
def api_delete_stock_transaction(tx_id):
    try:
        if stock_model.delete_transaction(session['user_id'], tx_id):
            return jsonify({"success": True})
        abort(404, "找不到此明細或刪除失敗")
    except ValueError as e:
        abort(400, str(e))
