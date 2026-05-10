from flask import Blueprint, render_template, request, jsonify, abort, session, redirect
from app.models.expense import ExpenseModel
from app.models.category import CategoryModel
from app.models.account import AccountModel
from app.models.db import get_db
from datetime import datetime

main_bp = Blueprint("main", __name__)
expense_model = ExpenseModel()
category_model = CategoryModel()
account_model = AccountModel()

STOCK_CATEGORY = "股票交易"

@main_bp.before_request
def require_login():
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({"error": "未登入"}), 401
        return redirect('/login')

def get_user_budget(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT monthly_budget FROM users WHERE id = ?", (user_id,)).fetchone()
        return row['monthly_budget'] if row else 0

@main_bp.route("/")
def index():
    user_id = session['user_id']
    expenses = expense_model.get_all(user_id)
    categories = category_model.get_by_user(user_id)
    
    cat_dict = {c["name"]: c for c in categories}
    
    total_balance = 0
    budget_used = 0
    
    account_balances = {}
    
    for e in expenses:
        cat_info = cat_dict.get(e["category"], {})
        is_asset = cat_info.get("is_asset", 1)
        in_budget = cat_info.get("in_budget", 1)
        
        if is_asset:
            if e["type"] == "income":
                total_balance += e["amount"]
            elif e["type"] == "expense":
                total_balance -= e["amount"]
                
        if e["type"] == "expense" and in_budget:
            budget_used += e["amount"]
            
        # 計算各帳戶餘額
        acc_id = e.get("account_id")
        to_acc_id = e.get("to_account_id")
        
        if acc_id not in account_balances: account_balances[acc_id] = 0
        if to_acc_id not in account_balances: account_balances[to_acc_id] = 0
        
        if e["type"] == "income":
            account_balances[acc_id] += e["amount"]
        elif e["type"] == "expense":
            account_balances[acc_id] -= e["amount"]
        elif e["type"] == "transfer":
            account_balances[acc_id] -= e["amount"]
            account_balances[to_acc_id] += e["amount"]

    # 分群處理類別
    grouped_categories = {}
    for c in categories:
        g = c.get("group_name", "未分類") or "未分類"
        if g not in grouped_categories:
            grouped_categories[g] = []
        grouped_categories[g].append(c)

    monthly_budget = get_user_budget(user_id)
    accounts = account_model.get_by_user(user_id)
    
    # Build account lookup for template
    account_map = {a['id']: a for a in accounts}
    
    # 供手動選擇的帳戶與類別 (排除股票專用)
    selectable_accounts = [a for a in accounts if a['name'] != STOCK_CATEGORY]
    
    filtered_grouped_categories = {}
    for g, cats in grouped_categories.items():
        if g == "未分類": continue
        filtered_cats = [c for c in cats if c['name'] != STOCK_CATEGORY]
        if filtered_cats:
            filtered_grouped_categories[g] = filtered_cats
            
    if "未分類" in grouped_categories:
        filtered_cats = [c for c in grouped_categories["未分類"] if c['name'] != STOCK_CATEGORY]
        if filtered_cats:
            filtered_grouped_categories["未分類"] = filtered_cats
    
    return render_template(
        "index.html", 
        expenses=expenses, 
        grouped_categories=filtered_grouped_categories, 
        categories=categories,
        total_balance=total_balance, 
        budget_used=budget_used,
        monthly_budget=monthly_budget,
        accounts=selectable_accounts,
        all_accounts=accounts,
        account_map=account_map,
        account_balances=account_balances,
        username=session['username']
    )

@main_bp.route("/charts")
def charts():
    user_id = session['user_id']
    expenses = expense_model.get_all(user_id)
    categories = category_model.get_by_user(user_id)
    cat_dict = {c["name"]: c for c in categories}
    
    accounts = account_model.get_by_user(user_id)
    account_map = {a["id"]: a for a in accounts}
    
    account_balances = {}
    for e in expenses:
        cat_info = cat_dict.get(e["category"], {})
        is_asset = cat_info.get("is_asset", 1)
        if is_asset:
            acc_id = e.get("account_id", 0)
            if acc_id not in account_balances: account_balances[acc_id] = 0
            if e["type"] == "income": account_balances[acc_id] += e["amount"]
            elif e["type"] == "expense": account_balances[acc_id] -= e["amount"]
            elif e["type"] == "transfer":
                account_balances[acc_id] -= e["amount"]
                to_acc_id = e.get("to_account_id", 0)
                if to_acc_id not in account_balances: account_balances[to_acc_id] = 0
                account_balances[to_acc_id] += e["amount"]

    cash = 0
    liabilities = 0
    for acc_id, balance in account_balances.items():
        if acc_id in account_map and account_map[acc_id].get("type") == "liability":
            liabilities += balance
        else:
            cash += balance
            
    # 如果有建立股票交易帳戶，其餘額會計入 cash，但為了避免重複計算總資產，我們在前端應該注意
    # 或者乾脆在這裡扣除「股票交易」的餘額？
    # 如果「股票交易」是資產，會被加進 cash 中，那麼 charts 中的 cash 就會包含股票的成本。
    # 所以我們要從 cash 扣除「股票交易」帳戶的餘額
    stock_account_id = None
    for acc in accounts:
        if acc["name"] == "股票交易":
            stock_account_id = acc["id"]
            break
            
    if stock_account_id and stock_account_id in account_balances:
        cash -= account_balances[stock_account_id]
    
    stock_value = 0
    with get_db() as conn:
        rows = conn.execute("SELECT shares, current_price FROM stocks WHERE user_id = ?", (user_id,)).fetchall()
        stock_value = sum(r['shares'] * r['current_price'] for r in rows)
        
    return render_template("charts.html", username=session['username'], cash=cash, liabilities=liabilities, stock_value=stock_value)

@main_bp.route("/api/user/budget", methods=["POST"])
def update_budget():
    data = request.get_json(force=True)
    if "monthly_budget" not in data: abort(400, description="缺少必要欄位")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET monthly_budget = ? WHERE id = ?", (float(data["monthly_budget"]), session['user_id']))
    return jsonify({"success": True})

@main_bp.route("/api/expenses", methods=["GET"])
def api_list():
    return jsonify(expense_model.get_all(session['user_id']))

@main_bp.route("/api/expenses", methods=["POST"])
def api_create():
    data = request.get_json(force=True)
    required = ("title", "amount", "category", "date")
    if not all(k in data for k in required): abort(400, description="缺少必要欄位")

    req_type = data.get("type", "expense")
    new_id = expense_model.create(
        user_id=session['user_id'],
        title=data["title"],
        amount=data["amount"],
        category=data["category"] if req_type != "transfer" else "",
        date=data["date"],
        note=data.get("note", ""),
        type=req_type,
        account_id=int(data.get("account_id", 0)),
        to_account_id=int(data.get("to_account_id", 0)) if req_type == "transfer" else None
    )
    return jsonify({"success": True, "id": new_id}), 201

@main_bp.route("/api/expenses/<expense_id>", methods=["GET"])
def api_get(expense_id):
    doc = expense_model.get_by_id(expense_id, session['user_id'])
    if not doc: abort(404, description="找不到此筆明細")
    return jsonify(doc)

@main_bp.route("/api/expenses/<expense_id>", methods=["PUT"])
def api_update(expense_id):
    doc = expense_model.get_by_id(expense_id, session['user_id'])
    if not doc: abort(404, "找不到此筆明細")
    if doc.get("category") == "股票交易": abort(403, "股票交易產生的明細請至股票專區操作")
    
    data = request.get_json(force=True)
    req_type = data.get("type", doc.get("type"))
    if req_type != "transfer":
        data["to_account_id"] = 0
        
    if not expense_model.update(expense_id, session['user_id'], data):
        abort(404, description="更新失敗或找不到此筆明細")
    return jsonify({"success": True})

@main_bp.route("/api/expenses/<expense_id>", methods=["DELETE"])
def api_delete(expense_id):
    doc = expense_model.get_by_id(expense_id, session['user_id'])
    if not doc: abort(404, "找不到此筆明細")
    if doc.get("category") == "股票交易": abort(403, "股票交易產生的明細請至股票專區操作")
    
    if not expense_model.delete(expense_id, session['user_id']):
        abort(404, description="找不到此筆明細")
    return jsonify({"success": True})

@main_bp.route("/api/budget")
def api_get_budget():
    user_id = session['user_id']
    now = datetime.now()
    year = int(request.args.get('year', now.year))
    month = int(request.args.get('month', now.month))
    with get_db() as conn:
        row = conn.execute(
            "SELECT amount FROM user_monthly_budgets WHERE user_id=? AND year=? AND month=?",
            (user_id, year, month)
        ).fetchone()
        total = float(row['amount']) if row else 0.0
        cat_rows = conn.execute(
            "SELECT category_id, amount FROM cat_monthly_budgets WHERE user_id=? AND year=? AND month=?",
            (user_id, year, month)
        ).fetchall()
    return jsonify({
        'total_budget': total,
        'categories': [{'id': r['category_id'], 'amount': float(r['amount'])} for r in cat_rows]
    })

@main_bp.route("/api/budget", methods=["POST"])
def api_save_budget():
    user_id = session['user_id']
    data = request.get_json(force=True)
    now = datetime.now()
    year = int(data.get('year', now.year))
    month = int(data.get('month', now.month))
    total = float(data.get('total_budget', 0))
    cats = data.get('categories', [])
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO user_monthly_budgets (user_id, year, month, amount) VALUES (?,?,?,?)",
            (user_id, year, month, total)
        )
        for cat in cats:
            conn.execute(
                "INSERT OR REPLACE INTO cat_monthly_budgets (user_id, category_id, year, month, amount) VALUES (?,?,?,?,?)",
                (user_id, int(cat['id']), year, month, float(cat.get('amount', 0)))
            )
    return jsonify({'success': True})

@main_bp.route("/api/charts/monthly")
def api_monthly():
    return jsonify(expense_model.get_monthly_summary(session['user_id']))

@main_bp.route("/api/charts/category")
def api_category():
    return jsonify(expense_model.get_category_summary(session['user_id']))

@main_bp.app_errorhandler(400)
def bad_request(e): return jsonify({"error": str(e.description)}), 400
@main_bp.app_errorhandler(403)
def forbidden(e): return jsonify({"error": str(e.description)}), 403
@main_bp.app_errorhandler(404)
def not_found(e): return jsonify({"error": str(e.description)}), 404