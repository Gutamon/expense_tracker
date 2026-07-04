from datetime import datetime, date
from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA
from app.models.expense import ExpenseModel
from app.models.account import AccountModel

expense_model = ExpenseModel()


class DebtModel:

    # ── Credit Cards ──────────────────────────────────────────────────────────

    def get_credit_cards(self) -> list:
        accounts = read_csv("accounts.csv")
        cards = []
        for r in accounts:
            sub_type = r.get("sub_type", "")
            is_cc = sub_type == "信用卡" or (not sub_type and r.get("type") == "liability")
            if not is_cc:
                continue
            card = dict(r)
            card.update(self._card_billing(card))
            card["balance"] = card["total_outstanding"]   # 累計未繳，供 summary 使用
            card["recent_txs"] = self._card_recent_txs(r["id"])
            cards.append(card)
        return cards

    @staticmethod
    def _cycle_start(billing_day: int) -> date:
        """Most recent occurrence of the billing start day on/before today."""
        billing_day = max(1, min(int(billing_day or 1), 28))
        today = date.today()
        if today.day >= billing_day:
            return date(today.year, today.month, billing_day)
        y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return date(y, m, billing_day)

    @staticmethod
    def _due_date(cycle_start: date, due_day: int) -> str:
        """Payment due date for the statement that closed at cycle_start."""
        due_day = max(1, min(int(due_day), 28))
        y, m = cycle_start.year, cycle_start.month
        if due_day < cycle_start.day:
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        return date(y, m, due_day).isoformat()

    def _card_billing(self, card: dict) -> dict:
        """Compute billing-cycle figures for a credit card.

        charges = expenses on the card; repays = transfers into the card.
        Statement closes at the billing start day: everything dated before the
        current cycle start is 本期應繳 (this period's amount due / prior carry-over);
        everything on/after is 本期新增消費 (not yet billed).
        """
        account_id = str(card.get("id"))
        expenses = read_csv("expenses.csv")

        charges, repays = [], []   # each: (date_str, amount)
        for e in expenses:
            if e.get("type") == "expense" and str(e.get("account_id")) == account_id:
                charges.append((e.get("date", ""), float(e.get("amount") or 0)))
            elif e.get("type") == "transfer" and str(e.get("to_account_id")) == account_id:
                repays.append((e.get("date", ""), float(e.get("to_amount") or e.get("amount") or 0)))

        cs = self._cycle_start(card.get("billing_start_day") or 1).isoformat()

        # opening_balance is stored negative for liabilities (e.g. -1000 means 1000 owed)
        initial_debt = max(-float(card.get("opening_balance") or 0), 0)

        charges_before = initial_debt + sum(a for d, a in charges if d and d < cs)
        repays_before = sum(a for d, a in repays if d and d < cs)
        cycle_charges = sum(a for d, a in charges if d and d >= cs)
        cycle_repaid = sum(a for d, a in repays if d and d >= cs)

        statement_due = max(round(charges_before - repays_before, 2), 0)
        total_outstanding = round(
            initial_debt + sum(a for _, a in charges) - sum(a for _, a in repays), 2)

        pct = float(card.get("min_payment_pct") or 0)
        floor = float(card.get("min_payment_floor") or 0)
        if statement_due > 0:
            min_payment = min(round(max(statement_due * pct / 100, floor), 2), statement_due)
        else:
            min_payment = 0

        due_day = int(card.get("payment_due_day") or 0)
        due_date = self._due_date(self._cycle_start(card.get("billing_start_day") or 1), due_day) if due_day else ""

        if total_outstanding <= 0:
            status = "paid_off"
        elif statement_due <= 0:
            status = "current_clear"            # 本期應繳已繳清，僅剩未出帳消費
        elif min_payment > 0 and cycle_repaid >= min_payment:
            status = "min_paid"
        elif cycle_repaid > 0:
            status = "partial"
        else:
            status = "unpaid"

        return {
            "cycle_start": cs,
            "statement_due": statement_due,
            "cycle_charges": round(cycle_charges, 2),
            "cycle_repaid": round(cycle_repaid, 2),
            "total_outstanding": total_outstanding,
            "min_payment": min_payment,
            "due_date": due_date,
            "status": status,
        }

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

    def add_interest_charge(self, account_id: int, amount: float, date: str, note: str) -> int:
        """Record a manually-entered revolving-interest charge on the card.

        Stored as an ordinary expense on the card so it flows into the
        outstanding balance and net-worth calculations automatically.
        """
        accounts = read_csv("accounts.csv")
        card = next((a for a in accounts if str(a.get("id")) == str(account_id)), None)
        title = f"循環利息（{card['name']}）" if card else "循環利息"
        new_id = expense_model.create_with_links(
            title=title, amount=amount, category="循環利息",
            date=date, note=note or "", type="expense",
            account_id=int(account_id),
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

        today = date.today()
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

            # Compute accrued interest estimate
            rate = float(loan.get("interest_rate") or 0)
            remaining = float(loan.get("remaining") or 0)
            start_str = loan.get("start_date", "")
            days_elapsed = 0
            accrued_interest = 0.0
            if rate > 0 and remaining > 0 and start_str:
                try:
                    start = date.fromisoformat(start_str)
                    days_elapsed = max((today - start).days, 0)
                    accrued_interest = round(remaining * (rate / 100) / 365 * days_elapsed, 2)
                except ValueError:
                    pass
            loan["days_elapsed"] = days_elapsed
            loan["accrued_interest"] = accrued_interest

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
                for key in ["name", "interest_rate", "start_date", "due_date", "status", "note"]:
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
        target = next((r for r in rows if str(r.get("id")) == loan_id), None)
        rows = [r for r in rows if str(r.get("id")) != loan_id]
        write_csv("loans.csv", rows, SCHEMA["loans.csv"])
        if target:
            linked = int(target.get("linked_account_id") or 0)
            if linked:
                AccountModel().delete(linked)
        return True

    def add_payment(self, loan_id: int, amount: float, date: str, note: str, account_id: int = None) -> int:
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
            account_id=int(account_id or loan.get("account_id", 0)),
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
