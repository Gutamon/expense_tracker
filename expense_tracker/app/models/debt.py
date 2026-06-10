from datetime import datetime
from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA
from app.models.expense import ExpenseModel

expense_model = ExpenseModel()


class DebtModel:

    # ── Credit Cards ──────────────────────────────────────────────────────────

    def get_credit_cards(self) -> list:
        accounts = read_csv("accounts.csv")
        cards = []
        for r in accounts:
            if r.get("type") != "liability":
                continue
            card = dict(r)
            card["balance"] = self._card_balance(r["id"])
            card["recent_txs"] = self._card_recent_txs(r["id"])
            cards.append(card)
        return cards

    def _card_balance(self, account_id) -> float:
        expenses = read_csv("expenses.csv")
        account_id = str(account_id)
        charged = sum(
            float(e.get("amount") or 0)
            for e in expenses
            if str(e.get("account_id")) == account_id and e.get("type") == "expense"
        )
        repaid = sum(
            float(e.get("amount") or 0)
            for e in expenses
            if str(e.get("to_account_id")) == account_id and e.get("type") == "transfer"
        )
        return round(charged - repaid, 2)

    def _card_recent_txs(self, account_id, limit: int = 10) -> list:
        expenses = read_csv("expenses.csv")
        account_id = str(account_id)
        txs = [
            e for e in expenses
            if str(e.get("account_id")) == account_id and e.get("type") == "expense"
        ]
        txs.sort(key=lambda e: (e.get("date", ""), e.get("id", "")), reverse=True)
        return txs[:limit]

    def repay_credit_card(self, from_account_id: int, to_account_id: int,
                          amount: float, date: str, note: str) -> int:
        accounts = read_csv("accounts.csv")
        card = next((a for a in accounts if str(a.get("id")) == str(to_account_id)), None)
        title = f"信用卡還款（{card['name']}）" if card else "信用卡還款"
        new_id = expense_model.create_with_links(
            title=title, amount=amount, category="信用卡還款",
            date=date, note=note or "", type="transfer",
            account_id=int(from_account_id), to_account_id=int(to_account_id),
        )
        return new_id

    # ── Loans ─────────────────────────────────────────────────────────────────

    def get_loans(self) -> list:
        loans = read_csv("loans.csv")
        payments = read_csv("loan_payments.csv")
        accounts = {str(a["id"]): a for a in read_csv("accounts.csv")}

        payment_map = {}
        for p in payments:
            lid = str(p.get("loan_id"))
            payment_map.setdefault(lid, []).append(p)

        result = []
        for loan in sorted(loans, key=lambda l: l.get("created_at", ""), reverse=True):
            loan = dict(loan)
            lid = str(loan.get("id"))
            loan_payments = sorted(
                payment_map.get(lid, []),
                key=lambda p: (p.get("date", ""), p.get("id", "")),
                reverse=True
            )
            loan["payments"] = loan_payments
            loan["payment_count"] = len(loan_payments)
            acc = accounts.get(str(loan.get("account_id")), {})
            loan["account_name"] = acc.get("name", "未知")
            loan["account_icon"] = acc.get("icon", "💰")
            result.append(loan)
        return result

    def get_loan_by_id(self, loan_id: int) -> dict | None:
        loans = read_csv("loans.csv")
        return next((l for l in loans if str(l.get("id")) == str(loan_id)), None)

    def create_loan(self, name: str, loan_type: str, principal: float,
                    interest_rate: float, start_date: str, due_date,
                    account_id: int, note: str) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = read_csv("loans.csv")
        loan_id = next_id(rows)
        rows.append({
            "id": loan_id,
            "name": name,
            "type": loan_type,
            "principal": principal,
            "remaining": principal,
            "interest_rate": interest_rate,
            "start_date": start_date,
            "due_date": due_date or "",
            "account_id": account_id,
            "status": "active",
            "note": note or "",
            "created_at": now,
        })
        write_csv("loans.csv", rows, SCHEMA["loans.csv"])

        if loan_type == "borrow":
            exp_type, category, title = "income", "借入款項", f"借入：{name}"
        else:
            exp_type, category, title = "expense", "借出款項", f"借出：{name}"

        expense_model.create_with_links(
            title=title, amount=principal, category=category,
            date=start_date, note=note or "", type=exp_type,
            account_id=int(account_id), loan_id=loan_id,
        )
        return loan_id

    def update_loan(self, loan_id: int, data: dict) -> bool:
        rows = read_csv("loans.csv")
        loan_id = str(loan_id)
        for r in rows:
            if str(r.get("id")) == loan_id:
                for key in ["name", "interest_rate", "due_date", "status", "note"]:
                    if key in data:
                        r[key] = data[key]
                write_csv("loans.csv", rows, SCHEMA["loans.csv"])
                return True
        return False

    def delete_loan(self, loan_id: int) -> bool:
        loan_id = str(loan_id)
        payments = read_csv("loan_payments.csv")
        if any(str(p.get("loan_id")) == loan_id for p in payments):
            return False

        expense_model.delete_where(loan_id=loan_id)

        rows = read_csv("loans.csv")
        rows = [r for r in rows if str(r.get("id")) != loan_id]
        write_csv("loans.csv", rows, SCHEMA["loans.csv"])
        return True

    def add_payment(self, loan_id: int, amount: float, date: str, note: str) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        loans = read_csv("loans.csv")
        loan_id_str = str(loan_id)
        loan = next((l for l in loans if str(l.get("id")) == loan_id_str), None)
        if not loan:
            return 0

        pay_rows = read_csv("loan_payments.csv")
        payment_id = next_id(pay_rows)
        pay_rows.append({
            "id": payment_id,
            "loan_id": loan_id,
            "amount": amount,
            "date": date,
            "note": note or "",
            "created_at": now,
        })
        write_csv("loan_payments.csv", pay_rows, SCHEMA["loan_payments.csv"])

        new_remaining = round(float(loan.get("remaining") or 0) - amount, 2)
        new_status = "closed" if new_remaining <= 0 else "active"
        for l in loans:
            if str(l.get("id")) == loan_id_str:
                l["remaining"] = new_remaining
                l["status"] = new_status
                break
        write_csv("loans.csv", loans, SCHEMA["loans.csv"])

        if loan.get("type") == "borrow":
            exp_type, category, title = "expense", "借款還款", f"還款：{loan['name']}"
        else:
            exp_type, category, title = "income", "借款回收", f"收款：{loan['name']}"

        expense_model.create_with_links(
            title=title, amount=amount, category=category,
            date=date, note=note or "", type=exp_type,
            account_id=int(loan.get("account_id", 0)),
            loan_payment_id=payment_id,
        )
        return payment_id

    def delete_payment(self, payment_id: int) -> bool:
        payment_id_str = str(payment_id)
        pay_rows = read_csv("loan_payments.csv")
        payment = next((p for p in pay_rows if str(p.get("id")) == payment_id_str), None)
        if not payment:
            return False

        pay_rows = [p for p in pay_rows if str(p.get("id")) != payment_id_str]
        write_csv("loan_payments.csv", pay_rows, SCHEMA["loan_payments.csv"])

        expense_model.delete_where(loan_payment_id=payment_id_str)

        loan_id = str(payment.get("loan_id"))
        loans = read_csv("loans.csv")
        for l in loans:
            if str(l.get("id")) == loan_id:
                new_remaining = round(float(l.get("remaining") or 0) + float(payment.get("amount") or 0), 2)
                l["remaining"] = new_remaining
                l["status"] = "active" if new_remaining > 0 else "closed"
                break
        write_csv("loans.csv", loans, SCHEMA["loans.csv"])
        return True
