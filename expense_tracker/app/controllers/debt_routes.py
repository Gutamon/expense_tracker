from flask import Blueprint, render_template, request, jsonify, abort
from app.models.debt import DebtModel
from app.models.account import AccountModel
from app.models import csv_store

debt_bp = Blueprint("debt", __name__)
debt_model = DebtModel()
account_model = AccountModel()


@debt_bp.route("/debts")
def debts_page():
    credit_cards = debt_model.get_credit_cards()
    loans = debt_model.get_loans()
    accounts = account_model.get_all()
    asset_accounts = [a for a in accounts if a.get("type") != "liability"]

    total_cc_outstanding = sum(c["balance"] for c in credit_cards if c["balance"] > 0)
    total_cycle_charges = sum(float(c.get("cycle_charges", 0)) for c in credit_cards)
    total_loan_owed = sum(
        float(l.get("remaining") or 0) + float(l.get("accrued_interest") or 0)
        for l in loans
        if l.get("type") == "borrow" and l.get("status") == "active"
    )
    total_loan_receivable = sum(
        float(l.get("remaining") or 0) + float(l.get("accrued_interest") or 0)
        for l in loans
        if l.get("type") == "lend" and l.get("status") == "active"
    )

    return render_template(
        "debts.html",
        credit_cards=credit_cards,
        loans=loans,
        asset_accounts=asset_accounts,
        accounts=accounts,
        username="",
        total_cc_outstanding=total_cc_outstanding,
        total_cycle_charges=total_cycle_charges,
        total_loan_owed=total_loan_owed,
        total_loan_receivable=total_loan_receivable,
    )


# ── Credit Card API ───────────────────────────────────────────────────────────

@debt_bp.route("/api/debts/cc/repay", methods=["POST"])
def api_cc_repay():
    data = request.get_json(force=True)
    from_id = data.get("from_account_id")
    to_id = data.get("to_account_id")
    amount = data.get("amount")
    date = data.get("date")
    if not all([from_id, to_id, amount, date]):
        abort(400, description="缺少必要欄位")
    expense_id = debt_model.repay_credit_card(
        from_account_id=int(from_id),
        to_account_id=int(to_id),
        amount=float(amount),
        date=date,
        note=data.get("note", ""),
    )
    return jsonify({"success": True, "expense_id": expense_id}), 201


@debt_bp.route("/api/debts/cc/interest", methods=["POST"])
def api_cc_interest():
    data = request.get_json(force=True)
    account_id = data.get("account_id")
    amount = data.get("amount")
    date = data.get("date")
    if not all([account_id, amount, date]):
        abort(400, description="缺少必要欄位")
    expense_id = debt_model.add_interest_charge(
        account_id=int(account_id),
        amount=float(amount),
        date=date,
        note=data.get("note", ""),
    )
    return jsonify({"success": True, "expense_id": expense_id}), 201


# ── Loan API ──────────────────────────────────────────────────────────────────

@debt_bp.route("/api/debts/loans", methods=["GET"])
def api_loans_list():
    return jsonify(debt_model.get_loans())


@debt_bp.route("/api/debts/loans", methods=["POST"])
def api_loans_create():
    data = request.get_json(force=True)
    for f in ["name", "type", "principal", "start_date", "account_id"]:
        if not data.get(f):
            abort(400, description=f"缺少欄位：{f}")
    if data["type"] not in ("borrow", "lend"):
        abort(400, description="type 必須為 borrow 或 lend")
    loan_name = data["name"].strip()
    loan_type = data["type"]
    loan_id = debt_model.create_loan(
        name=loan_name,
        loan_type=loan_type,
        principal=float(data["principal"]),
        interest_rate=float(data.get("interest_rate", 0)),
        start_date=data["start_date"],
        due_date=data.get("due_date") or None,
        account_id=int(data["account_id"]),
        note=data.get("note", ""),
    )

    acc_type = "liability" if loan_type == "borrow" else "asset"
    linked_acc_id = account_model.create(name=loan_name, icon="🤝", type=acc_type,
                                         sub_type="借貸", is_asset=1, currency="TWD")
    rows = csv_store.read_csv("loans.csv")
    for r in rows:
        if str(r.get("id")) == str(loan_id):
            r["linked_account_id"] = int(linked_acc_id)
            break
    csv_store.write_csv("loans.csv", rows, csv_store.SCHEMA["loans.csv"])

    return jsonify({"success": True, "id": loan_id}), 201


@debt_bp.route("/api/debts/loans/<int:loan_id>", methods=["PUT"])
def api_loans_update(loan_id):
    data = request.get_json(force=True)
    if not debt_model.update_loan(loan_id, data):
        abort(404, description="更新失敗")
    if "name" in data:
        rows = csv_store.read_csv("loans.csv")
        loan = next((r for r in rows if str(r.get("id")) == str(loan_id)), None)
        if loan:
            linked = int(loan.get("linked_account_id") or 0)
            if linked:
                account_model.update(linked, {"name": data["name"]})
    return jsonify({"success": True})


@debt_bp.route("/api/debts/loans/<int:loan_id>", methods=["DELETE"])
def api_loans_delete(loan_id):
    result = debt_model.delete_loan(loan_id)
    if result is False:
        abort(400, description="此借貸已有還款紀錄，無法刪除")
    return jsonify({"success": True})


@debt_bp.route("/api/debts/loans/<int:loan_id>/payments", methods=["POST"])
def api_payments_create(loan_id):
    data = request.get_json(force=True)
    if not data.get("amount") or not data.get("date"):
        abort(400, description="缺少金額或日期")
    payment_id = debt_model.add_payment(
        loan_id=loan_id,
        amount=float(data["amount"]),
        date=data["date"],
        note=data.get("note", ""),
        account_id=int(data["account_id"]) if data.get("account_id") else None,
    )
    if not payment_id:
        abort(404, description="借貸不存在")
    return jsonify({"success": True, "id": payment_id}), 201


@debt_bp.route("/api/debts/payments/<int:payment_id>", methods=["DELETE"])
def api_payments_delete(payment_id):
    if not debt_model.delete_payment(payment_id):
        abort(404, description="還款紀錄不存在")
    return jsonify({"success": True})
