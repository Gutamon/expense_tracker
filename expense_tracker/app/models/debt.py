from datetime import datetime
from app.models.db import get_db


class DebtModel:

    # ── Credit Cards ─────────────────────────────────────────────────────────

    def get_credit_cards(self, user_id: int) -> list:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts WHERE user_id = ? AND type = 'liability' ORDER BY sort_order, id",
                (user_id,)
            ).fetchall()
            cards = []
            for r in rows:
                card = dict(r)
                card['balance'] = self._card_balance(conn, user_id, r['id'])
                card['recent_txs'] = self._card_recent_txs(conn, user_id, r['id'])
                cards.append(card)
            return cards

    def _card_balance(self, conn, user_id: int, account_id: int) -> float:
        charged = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND account_id=? AND type='expense'",
            (user_id, account_id)
        ).fetchone()['s']
        repaid = conn.execute(
            "SELECT COALESCE(SUM(amount),0) as s FROM expenses WHERE user_id=? AND to_account_id=? AND type='transfer'",
            (user_id, account_id)
        ).fetchone()['s']
        return round(charged - repaid, 2)

    def _card_recent_txs(self, conn, user_id: int, account_id: int, limit: int = 10) -> list:
        rows = conn.execute(
            """SELECT id, title, amount, category, date, type, to_account_id, note
               FROM expenses WHERE user_id=? AND account_id=? AND type='expense'
               ORDER BY date DESC, id DESC LIMIT ?""",
            (user_id, account_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def repay_credit_card(self, user_id: int, from_account_id: int, to_account_id: int,
                          amount: float, date: str, note: str) -> int:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as conn:
            card_name = conn.execute(
                "SELECT name FROM accounts WHERE id=? AND user_id=?", (to_account_id, user_id)
            ).fetchone()
            title = f"信用卡還款（{card_name['name']}）" if card_name else "信用卡還款"
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO expenses
                   (user_id, title, amount, category, date, note, created_at, type, account_id, to_account_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, title, amount, '信用卡還款', date, note or '', now,
                 'transfer', from_account_id, to_account_id)
            )
            return cursor.lastrowid

    # ── Loans ─────────────────────────────────────────────────────────────────

    def get_loans(self, user_id: int) -> list:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM loans WHERE user_id=? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
            loans = []
            for r in rows:
                loan = dict(r)
                payments = conn.execute(
                    "SELECT * FROM loan_payments WHERE loan_id=? AND user_id=? ORDER BY date DESC, id DESC",
                    (r['id'], user_id)
                ).fetchall()
                loan['payments'] = [dict(p) for p in payments]
                loan['payment_count'] = len(loan['payments'])
                acc = conn.execute("SELECT name, icon FROM accounts WHERE id=?", (r['account_id'],)).fetchone()
                loan['account_name'] = acc['name'] if acc else '未知'
                loan['account_icon'] = acc['icon'] if acc else '💰'
                loans.append(loan)
            return loans

    def get_loan_by_id(self, user_id: int, loan_id: int) -> dict | None:
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM loans WHERE id=? AND user_id=?", (loan_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def get_payments(self, user_id: int, loan_id: int = None) -> list:
        with get_db() as conn:
            if loan_id:
                rows = conn.execute(
                    "SELECT * FROM loan_payments WHERE user_id=? AND loan_id=? ORDER BY date DESC, id DESC",
                    (user_id, loan_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM loan_payments WHERE user_id=? ORDER BY date DESC, id DESC",
                    (user_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    def create_loan(self, user_id: int, name: str, loan_type: str, principal: float,
                    interest_rate: float, start_date: str, due_date: str | None,
                    account_id: int, note: str) -> int:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO loans
                   (user_id, name, type, principal, remaining, interest_rate, start_date, due_date, account_id, status, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (user_id, name, loan_type, principal, principal, interest_rate,
                 start_date, due_date or None, account_id, 'active', note or '', now)
            )
            loan_id = cursor.lastrowid

            # Sync to expenses: borrow=income (received money), lend=expense (gave money)
            if loan_type == 'borrow':
                exp_type = 'income'
                category = '借入款項'
                title = f"借入：{name}"
            else:
                exp_type = 'expense'
                category = '借出款項'
                title = f"借出：{name}"

            cursor.execute(
                """INSERT INTO expenses
                   (user_id, title, amount, category, date, note, created_at, type, account_id, loan_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, title, principal, category, start_date, note or '', now,
                 exp_type, account_id, loan_id)
            )
            return loan_id

    def update_loan(self, user_id: int, loan_id: int, data: dict) -> bool:
        fields, values = [], []
        for key in ['name', 'interest_rate', 'due_date', 'status', 'note']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if not fields:
            return False
        values.extend([loan_id, user_id])
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE loans SET {', '.join(fields)} WHERE id=? AND user_id=?", values
            )
            return cursor.rowcount > 0

    def delete_loan(self, user_id: int, loan_id: int) -> bool:
        with get_db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) as c FROM loan_payments WHERE loan_id=? AND user_id=?",
                (loan_id, user_id)
            ).fetchone()['c']
            if count > 0:
                return False
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM expenses WHERE loan_id=? AND user_id=?", (loan_id, user_id)
            )
            cursor.execute(
                "DELETE FROM loans WHERE id=? AND user_id=?", (loan_id, user_id)
            )
            return cursor.rowcount > 0

    def add_payment(self, user_id: int, loan_id: int, amount: float, date: str, note: str) -> int:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as conn:
            loan = conn.execute(
                "SELECT * FROM loans WHERE id=? AND user_id=?", (loan_id, user_id)
            ).fetchone()
            if not loan:
                return 0

            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO loan_payments (user_id, loan_id, amount, date, note, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, loan_id, amount, date, note or '', now)
            )
            payment_id = cursor.lastrowid

            new_remaining = round(loan['remaining'] - amount, 2)
            new_status = 'closed' if new_remaining <= 0 else 'active'
            cursor.execute(
                "UPDATE loans SET remaining=?, status=? WHERE id=?",
                (new_remaining, new_status, loan_id)
            )

            # Sync expense: borrow repayment=expense (paying back), lend repayment=income (receiving back)
            if loan['type'] == 'borrow':
                exp_type = 'expense'
                category = '借款還款'
                title = f"還款：{loan['name']}"
            else:
                exp_type = 'income'
                category = '借款回收'
                title = f"收款：{loan['name']}"

            cursor.execute(
                """INSERT INTO expenses
                   (user_id, title, amount, category, date, note, created_at, type, account_id, loan_payment_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (user_id, title, amount, category, date, note or '', now,
                 exp_type, loan['account_id'], payment_id)
            )
            return payment_id

    def delete_payment(self, user_id: int, payment_id: int) -> bool:
        with get_db() as conn:
            payment = conn.execute(
                "SELECT * FROM loan_payments WHERE id=? AND user_id=?", (payment_id, user_id)
            ).fetchone()
            if not payment:
                return False

            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM loan_payments WHERE id=? AND user_id=?", (payment_id, user_id)
            )
            cursor.execute(
                "DELETE FROM expenses WHERE loan_payment_id=? AND user_id=?", (payment_id, user_id)
            )

            loan_id = payment['loan_id']
            loan = conn.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
            if loan:
                new_remaining = round(loan['remaining'] + payment['amount'], 2)
                new_status = 'active' if new_remaining > 0 else 'closed'
                cursor.execute(
                    "UPDATE loans SET remaining=?, status=? WHERE id=?",
                    (new_remaining, new_status, loan_id)
                )
            return True
