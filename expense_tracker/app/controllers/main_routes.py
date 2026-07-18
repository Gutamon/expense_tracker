import os
from flask import Blueprint, render_template, request, jsonify, abort, redirect, current_app, g
from app.models.expense import ExpenseModel
from app.models.category import CategoryModel, CategoryGroupModel
from app.models.account import AccountModel
from app.models.debt import DebtModel
from app.models import csv_store, user
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
        # Render the 全新開始 / 匯入還原 chooser directly — a redirect here would create
        # a second device before the browser stores the cookie from the first response.
        return render_template("onboarding.html")
    # Hand the device's 識別碼 to the shell so it can be mirrored into localStorage —
    # the iOS home-screen PWA drops the httponly cookie between cold launches, and
    # this lets the onboarding screen silently re-attach on next open. Read-only: the
    # shell loads several tabs as concurrent same-origin iframes, and generating a
    # code here (which can move the device's data folder on disk — see
    # user.ensure_sync_code) would race with those sibling requests. A code only
    # exists once the device has visited 設定, which mints it there instead.
    sync_code = user.sync_code_if_exists(csv_store.root_dir(), g.device_id) or ""
    return render_template("shell.html", sync_code=sync_code)


def _assets_version() -> str:
    """Latest mtime across templates/static, so any code change yields a new value.

    Embedding this in sw.js means the file's bytes change whenever the app changes —
    the browser detects that as a new service worker, installs it, and its activate
    handler wipes every older cache. No manual cache-version bump needed on deploy.
    """
    latest = 0
    for folder in (current_app.template_folder, current_app.static_folder):
        for dirpath, _, filenames in os.walk(folder):
            for name in filenames:
                try:
                    latest = max(latest, int(os.path.getmtime(os.path.join(dirpath, name))))
                except OSError:
                    pass
    return str(latest)


@main_bp.route("/sw.js")
def service_worker():
    # Served from root so its scope covers the whole app (a /static/ path could only
    # control /static/). Service-Worker-Allowed relaxes the scope restriction.
    body = render_template("sw.js", version=_assets_version())
    resp = current_app.response_class(body, mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@main_bp.route("/home")
def index():
    if csv_store.is_first_run():
        return redirect("/onboarding")

    expenses = expense_model.get_all()
    categories = category_model.get_all()
    accounts = account_model.get_all()
    account_map = {a["id"]: a for a in accounts}

    cat_dict = {c["name"]: c for c in categories}
    cat_by_id = {int(c["id"]): c for c in categories if c.get("id")}

    # Resolve each row's display category live from its category_id, so a rename在
    # 設定頁 shows immediately without rewriting expenses. Legacy rows (no id) keep
    # their stored name. cat_info below is looked up by id first for the same reason.
    for e in expenses:
        cid = int(e.get("category_id") or 0)
        if cid and cid in cat_by_id:
            e["category"] = cat_by_id[cid]["name"]

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
        cid = int(e.get("category_id") or 0)
        cat_info = cat_by_id.get(cid) or cat_dict.get(e["category"], {})
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

    # 股票現值（原本顯示在圖表頁頂部，移到記帳頁的資產餘額區）
    stock_items = []
    for r in csv_store.read_csv("stocks.csv"):
        shares = float(r.get("shares") or 0)
        value = shares * float(r.get("current_price") or 0)
        if shares > 0 and value:
            stock_items.append({"name": r.get("name") or r.get("symbol") or "", "value": round(value, 2)})
    stock_value = round(sum(s["value"] for s in stock_items), 2)

    groups = CategoryGroupModel().get_all()

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
        stock_items=stock_items,
        stock_value=stock_value,
        groups=groups,
        username="",
    )


@main_bp.route("/charts")
def charts():
    expenses = expense_model.get_all()
    categories = category_model.get_all()
    accounts = account_model.get_all()

    # 原始資料直接注入模板，聚合與篩選（帳戶／群組／類別）全部在前端進行
    groups = CategoryGroupModel().get_all()
    history = csv_store.read_csv("monthly_history.csv")
    return render_template(
        "charts.html", username="",
        expenses=expenses, categories=categories, groups=groups,
        accounts=accounts, history=history,
    )


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
    # Resolve the display category name live from category_id (mirrors /home), so a
    # rename在設定頁 shows on the next client refresh without touching stored rows.
    rows = expense_model.get_all()
    cat_by_id = {int(c["id"]): c for c in category_model.get_all() if c.get("id")}
    for r in rows:
        cid = int(r.get("category_id") or 0)
        if cid in cat_by_id:
            r["category"] = cat_by_id[cid]["name"]
    return jsonify(rows)


def _resolve_category(data: dict, req_type: str) -> tuple:
    """Return (name, id) for an expense/income row from the request payload.

    Prefers an explicit category_id (the select now carries the id); falls back to
    resolving name+type against categories.csv. Storing both means identity travels
    with the id (filters, same-name 收入/支出) while the name stays for display/export.
    Transfers have no category."""
    if req_type == "transfer":
        return "", 0
    cats = category_model.get_all()
    by_id = {str(c["id"]): c for c in cats}
    cid = str(data.get("category_id") or "").strip()
    if cid and cid in by_id:
        return by_id[cid]["name"], int(cid)
    # No id given: match by name + type (the type keeps 同名不同型別 apart).
    name = (data.get("category") or "").strip()
    match = next((c for c in cats if c.get("name") == name and c.get("type") == req_type), None)
    match = match or next((c for c in cats if c.get("name") == name), None)
    return (name, int(match["id"]) if match else 0)


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

    cat_name, cat_id = _resolve_category(data, req_type)
    new_id = expense_model.create(
        title=data["title"],
        amount=data["amount"],
        category=cat_name,
        category_id=cat_id,
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

    # Re-resolve category so an edited name/type also updates the stored id (and a
    # transfer clears both). Only when the payload actually references a category.
    if req_type == "transfer":
        data["category"], data["category_id"] = "", 0
    elif "category" in data or "category_id" in data:
        data["category"], data["category_id"] = _resolve_category(data, req_type)

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


def _ym_key(r):
    return int(r.get("year") or 0) * 12 + int(r.get("month") or 0)


def _latest_amount_before_or_at(rows, key_field, key_value, year, month):
    """Among rows matching key_field==key_value with (year,month) <= target, return the
    amount from the most recent one that is non-zero. Used to carry a budget forward to
    months that were never explicitly set."""
    target = year * 12 + month
    candidates = [r for r in rows if str(r.get(key_field)) == str(key_value) and _ym_key(r) <= target and float(r.get("amount") or 0) != 0]
    if not candidates:
        return 0.0
    latest = max(candidates, key=_ym_key)
    return float(latest.get("amount") or 0)


@main_bp.route("/api/budget")
def api_get_budget():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))

    mb_rows = csv_store.read_csv("monthly_budgets.csv")
    row = next((r for r in mb_rows if int(r.get("year") or 0) == year and int(r.get("month") or 0) == month), None)
    if row:
        total = float(row["amount"])
    else:
        candidates = [r for r in mb_rows if _ym_key(r) <= year * 12 + month and float(r.get("amount") or 0) != 0]
        total = float(max(candidates, key=_ym_key)["amount"]) if candidates else 0.0

    cat_rows = csv_store.read_csv("cat_monthly_budgets.csv")
    cat_ids = {str(r["category_id"]) for r in cat_rows}
    cats = []
    for cid in cat_ids:
        exact = next((r for r in cat_rows if str(r.get("category_id")) == cid and int(r.get("year") or 0) == year and int(r.get("month") or 0) == month), None)
        amount = float(exact["amount"]) if exact else _latest_amount_before_or_at(cat_rows, "category_id", cid, year, month)
        cats.append({"id": cid, "amount": amount})

    grp_rows = csv_store.read_csv("group_monthly_budgets.csv")
    grp_ids = {str(r["group_id"]) for r in grp_rows}
    groups = []
    for gid in grp_ids:
        exact = next((r for r in grp_rows if str(r.get("group_id")) == gid and int(r.get("year") or 0) == year and int(r.get("month") or 0) == month), None)
        amount = float(exact["amount"]) if exact else _latest_amount_before_or_at(grp_rows, "group_id", gid, year, month)
        groups.append({"id": gid, "amount": amount})

    return jsonify({"total_budget": total, "categories": cats, "groups": groups})


@main_bp.route("/api/budget", methods=["POST"])
def api_save_budget():
    data = request.get_json(force=True)
    now = datetime.now()
    year = int(data.get("year", now.year))
    month = int(data.get("month", now.month))
    total = float(data.get("total_budget", 0))
    cats = data.get("categories", [])
    groups = data.get("groups", [])

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

    gmb_rows = csv_store.read_csv("group_monthly_budgets.csv")
    for grp in groups:
        group_id = str(grp["id"])
        existing_grp = next(
            (r for r in gmb_rows
             if str(r.get("group_id")) == group_id and int(r.get("year") or 0) == year and int(r.get("month") or 0) == month),
            None
        )
        if existing_grp:
            existing_grp["amount"] = float(grp.get("amount", 0))
        else:
            gmb_rows.append({
                "id": csv_store.next_id(gmb_rows),
                "group_id": group_id,
                "year": year,
                "month": month,
                "amount": float(grp.get("amount", 0)),
            })
    csv_store.write_csv("group_monthly_budgets.csv", gmb_rows, csv_store.SCHEMA["group_monthly_budgets.csv"])
    return jsonify({"success": True})


@main_bp.route("/api/budget/clear", methods=["POST"])
def api_clear_budget():
    """Remove this year-month's explicit budget rows (total/category/group) so the
    carry-forward logic falls back to the most recent prior non-zero setting, or to
    zero if none exists."""
    data = request.get_json(force=True)
    now = datetime.now()
    year = int(data.get("year", now.year))
    month = int(data.get("month", now.month))

    mb_rows = csv_store.read_csv("monthly_budgets.csv")
    mb_rows = [r for r in mb_rows if not (int(r.get("year") or 0) == year and int(r.get("month") or 0) == month)]
    csv_store.write_csv("monthly_budgets.csv", mb_rows, csv_store.SCHEMA["monthly_budgets.csv"])

    cmb_rows = csv_store.read_csv("cat_monthly_budgets.csv")
    cmb_rows = [r for r in cmb_rows if not (int(r.get("year") or 0) == year and int(r.get("month") or 0) == month)]
    csv_store.write_csv("cat_monthly_budgets.csv", cmb_rows, csv_store.SCHEMA["cat_monthly_budgets.csv"])

    gmb_rows = csv_store.read_csv("group_monthly_budgets.csv")
    gmb_rows = [r for r in gmb_rows if not (int(r.get("year") or 0) == year and int(r.get("month") or 0) == month)]
    csv_store.write_csv("group_monthly_budgets.csv", gmb_rows, csv_store.SCHEMA["group_monthly_budgets.csv"])
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
