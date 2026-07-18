from collections import defaultdict
from datetime import datetime
from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA


class ExpenseModel:
    def create(self, title: str, amount: float, category: str, date: str, note: str = "",
               type: str = "expense", account_id: int = 0, to_account_id: int = 0,
               to_amount: float = None, category_id: int = 0) -> str:
        rows = read_csv("expenses.csv")
        new_id = next_id(rows)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "id": new_id,
            "title": title,
            "amount": float(amount),
            "category": category,
            "category_id": int(category_id or 0),
            "date": date,
            "note": note or "",
            "created_at": created_at,
            "type": type,
            "account_id": account_id or 0,
            "to_account_id": to_account_id or 0,
            "to_amount": to_amount if to_amount is not None else "",
            "stock_transaction_id": "",
            "loan_id": "",
            "loan_payment_id": "",
        })
        write_csv("expenses.csv", rows, SCHEMA["expenses.csv"])
        return str(new_id)

    def create_with_links(self, title: str, amount: float, category: str, date: str,
                          note: str = "", type: str = "expense", account_id: int = 0,
                          to_account_id: int = 0, to_amount: float = None,
                          stock_transaction_id=None, loan_id=None, loan_payment_id=None,
                          category_id: int = 0) -> str:
        rows = read_csv("expenses.csv")
        new_id = next_id(rows)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "id": new_id,
            "title": title,
            "amount": float(amount),
            "category": category,
            "category_id": int(category_id or 0),
            "date": date,
            "note": note or "",
            "created_at": created_at,
            "type": type,
            "account_id": account_id or 0,
            "to_account_id": to_account_id or 0,
            "to_amount": to_amount if to_amount is not None else "",
            "stock_transaction_id": stock_transaction_id or "",
            "loan_id": loan_id or "",
            "loan_payment_id": loan_payment_id or "",
        })
        write_csv("expenses.csv", rows, SCHEMA["expenses.csv"])
        return str(new_id)

    def get_all(self, sort_by: str = "date", order: int = -1) -> list:
        if sort_by not in ["date", "amount", "category", "created_at", "type"]:
            sort_by = "date"
        rows = read_csv("expenses.csv")
        reverse = (order == -1)
        rows.sort(key=lambda r: (r.get(sort_by) or ""), reverse=reverse)
        return rows

    def get_by_id(self, expense_id: str) -> dict | None:
        rows = read_csv("expenses.csv")
        expense_id = str(expense_id)
        return next((r for r in rows if str(r.get("id")) == expense_id), None)

    _SKIP_CATS = frozenset({"股票交易", "期初餘額"})

    def get_monthly_summary(self) -> list:
        agg = defaultdict(float)

        for r in read_csv("expenses.csv"):
            if r.get("category") in self._SKIP_CATS:
                continue
            date = r.get("date", "")
            if len(date) < 7:
                continue
            try:
                year = int(date[:4])
                month = int(date[5:7])
            except ValueError:
                continue
            key = (year, month, r.get("type", ""))
            try:
                agg[key] += float(r.get("amount") or 0)
            except ValueError:
                pass

        for h in read_csv("monthly_history.csv"):
            t = h.get("type", "")
            if t not in ("income", "expense"):
                continue
            try:
                key = (int(h["year"]), int(h["month"]), t)
                agg[key] += float(h.get("amount") or 0)
            except (ValueError, KeyError):
                pass

        return [{"year": k[0], "month": k[1], "type": k[2], "total": v}
                for k, v in sorted(agg.items())]

    def get_category_summary(self, year: int = None, month: int = None) -> list:
        # Aggregate by category_id when present so rows sharing a name but not an id
        # (收入/支出 both「匯入」) stay separate, and renames在設定頁自動反映——名稱是即時
        # 從 categories.csv 解析的，不吃 expenses/history 內存的舊名稱。Legacy rows without
        # a category_id fall back to keying by their stored name.
        cat_by_id = {int(c["id"]): c for c in read_csv("categories.csv") if c.get("id")}

        def resolve_name(stored_name, cat_id):
            c = cat_by_id.get(int(cat_id or 0))
            return c["name"] if c else stored_name

        agg = defaultdict(float)  # (name, type) -> total

        for r in read_csv("expenses.csv"):
            if r.get("category") in self._SKIP_CATS:
                continue
            if year is not None or month is not None:
                date = r.get("date", "")
                if len(date) < 7:
                    continue
                try:
                    d_year = int(date[:4])
                    d_month = int(date[5:7])
                except ValueError:
                    continue
                if year is not None and d_year != year:
                    continue
                if month is not None and d_month != month:
                    continue
            name = resolve_name(r.get("category", ""), r.get("category_id"))
            key = (name, r.get("type", ""))
            try:
                agg[key] += float(r.get("amount") or 0)
            except ValueError:
                pass

        for h in read_csv("monthly_history.csv"):
            t = h.get("type", "")
            if t not in ("income", "expense"):
                continue
            try:
                h_year = int(h["year"])
                h_month = int(h["month"])
            except (ValueError, KeyError):
                continue
            if year is not None and h_year != year:
                continue
            if month is not None and h_month != month:
                continue
            name = resolve_name(h.get("category", ""), h.get("category_id"))
            key = (name, t)
            try:
                agg[key] += float(h.get("amount") or 0)
            except ValueError:
                pass

        return [{"category": k[0], "type": k[1], "total": v}
                for k, v in sorted(agg.items(), key=lambda x: -x[1])]

    def update(self, expense_id: str, data: dict) -> bool:
        rows = read_csv("expenses.csv")
        expense_id = str(expense_id)
        for r in rows:
            if str(r.get("id")) == expense_id:
                for key in ["title", "amount", "category", "category_id", "date", "note", "type",
                            "account_id", "to_account_id", "to_amount"]:
                    if key in data:
                        if key == "amount":
                            r[key] = float(data[key])
                        elif key in ["account_id", "to_account_id", "category_id"]:
                            r[key] = int(data[key]) if data[key] else 0
                        elif key == "to_amount":
                            r[key] = float(data[key]) if data[key] is not None else ""
                        else:
                            r[key] = data[key]
                write_csv("expenses.csv", rows, SCHEMA["expenses.csv"])
                return True
        return False

    def delete(self, expense_id: str) -> bool:
        rows = read_csv("expenses.csv")
        expense_id = str(expense_id)
        new_rows = [r for r in rows if str(r.get("id")) != expense_id]
        if len(new_rows) == len(rows):
            return False
        write_csv("expenses.csv", new_rows, SCHEMA["expenses.csv"])
        return True

    def delete_where(self, **kwargs) -> int:
        rows = read_csv("expenses.csv")
        new_rows = []
        deleted = 0
        for r in rows:
            match = all(str(r.get(k)) == str(v) for k, v in kwargs.items() if v is not None)
            if match:
                deleted += 1
            else:
                new_rows.append(r)
        if deleted:
            write_csv("expenses.csv", new_rows, SCHEMA["expenses.csv"])
        return deleted

    def update_where(self, match: dict, updates: dict) -> int:
        rows = read_csv("expenses.csv")
        updated = 0
        for r in rows:
            if all(str(r.get(k)) == str(v) for k, v in match.items() if v is not None):
                for k, v in updates.items():
                    r[k] = v
                updated += 1
        if updated:
            write_csv("expenses.csv", rows, SCHEMA["expenses.csv"])
        return updated
