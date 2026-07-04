from flask import Blueprint, render_template, request, jsonify, abort, redirect
from app.models.expense import ExpenseModel
from app.models.category import CategoryModel
from app.models.account import AccountModel
from app.models.debt import DebtModel
from app.models import csv_store
from app.models import rates as rates_model
from datetime import datetime

main_bp = Blueprint("main", __name__)
expense_model = ExpenseModel()
category_model = CategoryModel()
account_model = AccountModel()
debt_model = DebtModel()


@main_bp.route("/")
def shell():
    if csv_store.is_first_run():
        # Render directly — avoid a redirect that would create a second device
        # before the browser stores the cookie from the first response.
        return render_template("onboarding.html")
    return render_template("shell.html")


@main_bp.route("/home")
def index():
    if csv_store.is_first_run():
        return redirect("/onboarding")

    expenses = expense_model.get_all()
    categories = category_model.get_all()
    accounts = account_model.get_all()
    account_map = {a["id"]: a for a in accounts}

    cat_dict = {c["name"]: c for c in categories}

    total_balance = 0
    budget_used = 0
    account_balances = {}

    # Seed each account's balance from its opening_balance
    for acc in accounts:
        ob = float(acc.get("opening_balance") or 0)
        if ob:
            account_balances[acc["id"]] = ob
        if int(acc.get("is_asset") or 0):
            total_balance += ob

    for e in expenses:
        cat_info = cat_dict.get(e["category"], {})
        is_asset = int(cat_info.get("is_asset", 1) or 1)
        in_budget = int(cat_info.get("in_budget", 0) or 0) if cat_info else 0

        if is_asset:
            if e["type"] == "income":
                total_balance += float(e.get("amount") or 0)
            elif e["type"] == "expense":
                total_balance -= float(e.get("amount") or 0)

        if e["type"] == "expense" and in_budget:
            budget_used += float(e.get("amount") or 0)

        acc_id = e.get("account_id")
        to_acc_id = e.get("to_account_id")

        if acc_id not in account_balances: account_balances[acc_id] = 0
        if to_acc_id not in account_balances: account_balances[to_acc_id] = 0

        if e["type"] == "income":
            account_balances[acc_id] += float(e.get("amount") or 0)
        elif e["type"] == "expense":
            account_balances[acc_id] -= float(e.get("amount") or 0)
        elif e["type"] == "transfer":
            account_balances[acc_id] -= float(e.get("amount") or 0)
            account_balances[to_acc_id] += float(e.get("to_amount") or e.get("amount") or 0)

    # Convert each account's balance into TWD for the proportion bar / totals.
    rates = rates_model.get_rates()
    account_balances_twd = {}
    for acc in accounts:
        cur = acc.get("currency") or "TWD"
        account_balances_twd[acc["id"]] = rates_model.to_twd(
            account_balances.get(acc["id"], 0), cur, rates)

    # Initial "所選資產總額" (all accounts selected), in TWD. The client recomputes
    # this from the account filters, but rendering the converted value avoids a flash.
    total_balance = sum(account_balances_twd.values())

    # Loan net adjustment: lent-but-unreturned is a receivable asset (+),
    # borrowed-but-unrepaid is a liability (-). Both include accrued interest.
    loans = debt_model.get_loans()
    lend_net = sum(
        float(l.get("remaining") or 0) + float(l.get("accrued_interest") or 0)
        for l in loans if l.get("type") == "lend" and l.get("status") == "active"
    )
    borrow_net = sum(
        float(l.get("remaining") or 0) + float(l.get("accrued_interest") or 0)
        for l in loans if l.get("type") == "borrow" and l.get("status") == "active"
    )
    loan_net = round(lend_net - borrow_net, 2)
    total_balance = round(total_balance + loan_net, 2)

    grouped_categories = {}
    for c in categories:
        g = c.get("group_name", "未分類") or "未分類"
        grouped_categories.setdefault(g, []).append(c)

    monthly_budget = float(csv_store.get_setting("monthly_budget", 0) or 0)

    # Collect linked account IDs from stocks and loans — these should not appear
    # as options in the expense-entry dropdowns.
    linked_ids = set()
    for r in csv_store.read_csv("stocks.csv"):
        lid = int(r.get("linked_account_id") or 0)
        if lid:
            linked_ids.add(lid)
    for r in csv_store.read_csv("loans.csv"):
        lid = int(r.get("linked_account_id") or 0)
        if lid:
            linked_ids.add(lid)
    entry_accounts = [a for a in accounts if a["id"] not in linked_ids]
    cc_account_ids = [a["id"] for a in accounts
                      if a.get("sub_type") == "信用卡"
                      or (a.get("type") == "liability" and not a.get("sub_type"))]

    filtered_grouped_categories = {}
    for g, cats in grouped_categories.items():
        if g == "未分類": continue
        if cats: filtered_grouped_categories[g] = cats
    if "未分類" in grouped_categories and grouped_categories["未分類"]:
        filtered_grouped_categories["未分類"] = grouped_categories["未分類"]

    return render_template(
        "index.html",
        expenses=expenses,
        grouped_categories=filtered_grouped_categories,
        categories=categories,
        total_balance=total_balance,
        budget_used=budget_used,
        monthly_budget=monthly_budget,
        accounts=entry_accounts,
        all_accounts=accounts,
        account_map=account_map,
        account_balances=account_balances,
        account_balances_twd=account_balances_twd,
        rates=rates,
        rates_updated_at=rates_model.get_updated_at(),
        cc_account_ids=cc_account_ids,
        lend_net=lend_net,
        borrow_net=borrow_net,
        username="",
    )


@main_bp.route("/charts")
def charts():
    expenses = expense_model.get_all()
    categories = category_model.get_all()
    cat_dict = {c["name"]: c for c in categories}

    accounts = account_model.get_all()
    account_map = {a["id"]: a for a in accounts}

    account_balances = {}
    for acc in accounts:
        ob = float(acc.get("opening_balance") or 0)
        if ob:
            account_balances[acc["id"]] = ob

    for e in expenses:
        cat_info = cat_dict.get(e["category"], {})
        is_asset = int(cat_info.get("is_asset", 1) or 1)
        if is_asset:
            acc_id = e.get("account_id", 0)
            if acc_id not in account_balances: account_balances[acc_id] = 0
            if e["type"] == "income":   account_balances[acc_id] += float(e.get("amount") or 0)
            elif e["type"] == "expense": account_balances[acc_id] -= float(e.get("amount") or 0)
            elif e["type"] == "transfer":
                account_balances[acc_id] -= float(e.get("amount") or 0)
                to_acc_id = e.get("to_account_id", 0)
                if to_acc_id not in account_balances: account_balances[to_acc_id] = 0
                account_balances[to_acc_id] += float(e.get("to_amount") or e.get("amount") or 0)

    cash = 0
    liabilities = 0
    for acc_id, balance in account_balances.items():
        if acc_id in account_map and account_map[acc_id].get("type") == "liability":
            liabilities += balance
        else:
            cash += balance

    stock_rows = csv_store.read_csv("stocks.csv")
    stock_value = sum(float(r.get("shares") or 0) * float(r.get("current_price") or 0) for r in stock_rows)

    return render_template("charts.html", username="", cash=cash, liabilities=liabilities, stock_value=stock_value)


@main_bp.route("/api/user/budget", methods=["POST"])
def update_budget():
    data = request.get_json(force=True)
    if "monthly_budget" not in data: abort(400, description="缺少必要欄位")
    csv_store.set_setting("monthly_budget", float(data["monthly_budget"]))
    return jsonify({"success": True})


# ── Exchange rates ────────────────────────────────────────────────────────────

@main_bp.route("/api/rates", methods=["GET"])
def api_rates():
    return jsonify({"rates": rates_model.get_rates(),
                    "updated_at": rates_model.get_updated_at()})


@main_bp.route("/api/rates/refresh", methods=["POST"])
def api_rates_refresh():
    return jsonify(rates_model.refresh_rates())


# ── Balance correction ────────────────────────────────────────────────────────

@main_bp.route("/api/accounts/<account_id>/adjust-balance", methods=["POST"])
def api_adjust_balance(account_id):
    """Set an account's actual balance by nudging opening_balance (not income/expense)."""
    data = request.get_json(force=True)
    if "target" not in data:
        abort(400, description="缺少目標餘額")
    try:
        target = float(data["target"])
    except (ValueError, TypeError):
        abort(400, description="目標餘額格式錯誤")
    delta = account_model.adjust_opening_balance(account_id, target)
    if delta is None:
        abort(404, description="找不到此帳戶")
    return jsonify({"success": True, "delta": delta, "target": target})


@main_bp.route("/api/expenses", methods=["GET"])
def api_list():
    return jsonify(expense_model.get_all())


@main_bp.route("/api/expenses", methods=["POST"])
def api_create():
    data = request.get_json(force=True)
    required = ("title", "amount", "category", "date")
    if not all(k in data for k in required): abort(400, description="缺少必要欄位")

    req_type = data.get("type", "expense")
    to_amount = None

    if req_type == "transfer":
        to_amount_raw = data.get("to_amount")
        if to_amount_raw is not None:
            to_amount = float(to_amount_raw)

        from_acc_id = int(data.get("account_id", 0))
        to_acc_id_val = int(data.get("to_account_id", 0))
        if from_acc_id and to_acc_id_val:
            accounts = account_model.get_all()
            acc_map = {str(a["id"]): a for a in accounts}
            from_acc = acc_map.get(str(from_acc_id))
            to_acc = acc_map.get(str(to_acc_id_val))
            if from_acc and to_acc:
                from_cur = from_acc.get("currency") or "TWD"
                to_cur = to_acc.get("currency") or "TWD"
                if from_cur != to_cur and (from_acc.get("type") == "liability" or to_acc.get("type") == "liability"):
                    abort(400, description="跨幣別轉帳只允許在現金類帳戶之間進行")

    new_id = expense_model.create(
        title=data["title"],
        amount=data["amount"],
        category=data["category"] if req_type != "transfer" else "",
        date=data["date"],
        note=data.get("note", ""),
        type=req_type,
        account_id=int(data.get("account_id", 0)),
        to_account_id=int(data.get("to_account_id", 0)) if req_type == "transfer" else 0,
        to_amount=to_amount,
    )
    return jsonify({"success": True, "id": new_id}), 201


@main_bp.route("/api/expenses/<expense_id>", methods=["GET"])
def api_get(expense_id):
    doc = expense_model.get_by_id(expense_id)
    if not doc: abort(404, description="找不到此筆明細")
    return jsonify(doc)


@main_bp.route("/api/expenses/<expense_id>", methods=["PUT"])
def api_update(expense_id):
    doc = expense_model.get_by_id(expense_id)
    if not doc: abort(404, "找不到此筆明細")
    if doc.get("stock_transaction_id") or doc.get("category") == "股票交易":
        abort(403, "股票交易產生的明細請至股票專區操作")

    data = request.get_json(force=True)
    req_type = data.get("type", doc.get("type"))
    if req_type != "transfer":
        data["to_account_id"] = 0
        data["to_amount"] = None

    if not expense_model.update(expense_id, data):
        abort(404, description="更新失敗或找不到此筆明細")
    return jsonify({"success": True})


@main_bp.route("/api/expenses/<expense_id>", methods=["DELETE"])
def api_delete(expense_id):
    doc = expense_model.get_by_id(expense_id)
    if not doc: abort(404, "找不到此筆明細")
    if doc.get("stock_transaction_id") or doc.get("category") == "股票交易":
        abort(403, "股票交易產生的明細請至股票專區操作")

    if not expense_model.delete(expense_id):
        abort(404, description="找不到此筆明細")
    return jsonify({"success": True})


@main_bp.route("/api/budget")
def api_get_budget():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))

    mb_rows = csv_store.read_csv("monthly_budgets.csv")
    row = next((r for r in mb_rows if int(r.get("year") or 0) == year and int(r.get("month") or 0) == month), None)
    total = float(row["amount"]) if row else 0.0

    cat_rows = csv_store.read_csv("cat_monthly_budgets.csv")
    cats = [
        {"id": r["category_id"], "amount": float(r.get("amount") or 0)}
        for r in cat_rows
        if int(r.get("year") or 0) == year and int(r.get("month") or 0) == month
    ]
    return jsonify({"total_budget": total, "categories": cats})


@main_bp.route("/api/budget", methods=["POST"])
def api_save_budget():
    data = request.get_json(force=True)
    now = datetime.now()
    year = int(data.get("year", now.year))
    month = int(data.get("month", now.month))
    total = float(data.get("total_budget", 0))
    cats = data.get("categories", [])

    mb_rows = csv_store.read_csv("monthly_budgets.csv")
    existing = next((r for r in mb_rows if int(r.get("year") or 0) == year and int(r.get("month") or 0) == month), None)
    if existing:
        existing["amount"] = total
    else:
        mb_rows.append({"id": csv_store.next_id(mb_rows), "year": year, "month": month, "amount": total})
    csv_store.write_csv("monthly_budgets.csv", mb_rows, csv_store.SCHEMA["monthly_budgets.csv"])

    cmb_rows = csv_store.read_csv("cat_monthly_budgets.csv")
    for cat in cats:
        cat_id = str(cat["id"])
        existing_cat = next(
            (r for r in cmb_rows
             if str(r.get("category_id")) == cat_id and int(r.get("year") or 0) == year and int(r.get("month") or 0) == month),
            None
        )
        if existing_cat:
            existing_cat["amount"] = float(cat.get("amount", 0))
        else:
            cmb_rows.append({
                "id": csv_store.next_id(cmb_rows),
                "category_id": cat_id,
                "year": year,
                "month": month,
                "amount": float(cat.get("amount", 0)),
            })
    csv_store.write_csv("cat_monthly_budgets.csv", cmb_rows, csv_store.SCHEMA["cat_monthly_budgets.csv"])
    return jsonify({"success": True})


@main_bp.route("/api/charts/monthly")
def api_monthly():
    return jsonify(expense_model.get_monthly_summary())


@main_bp.route("/api/charts/category")
def api_category():
    year = request.args.get("year", type=int)
    month = request.args.get("month", type=int)
    return jsonify(expense_model.get_category_summary(year=year, month=month))


@main_bp.app_errorhandler(400)
def bad_request(e): return jsonify({"error": str(e.description)}), 400
@main_bp.app_errorhandler(403)
def forbidden(e): return jsonify({"error": str(e.description)}), 403
@main_bp.app_errorhandler(404)
def not_found(e): return jsonify({"error": str(e.description)}), 404
