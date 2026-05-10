from datetime import datetime
from app.models.db import get_db

class ExpenseModel:
    def create(self, user_id: int, title: str, amount: float, category: str, date: str, note: str = "", type: str = "expense", account_id: int = 0, to_account_id: int = 0) -> str:
        with get_db() as conn:
            cursor = conn.cursor()
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''
                INSERT INTO expenses (user_id, title, amount, category, date, note, created_at, type, account_id, to_account_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, title, float(amount), category, date, note, created_at, type, account_id, to_account_id))
            return str(cursor.lastrowid)

    def get_all(self, user_id: int, sort_by: str = "date", order: int = -1) -> list:
        order_dir = "DESC" if order == -1 else "ASC"
        if sort_by not in ["date", "amount", "category", "created_at", "type"]:
            sort_by = "date"
        with get_db() as conn:
            rows = conn.execute(f'SELECT * FROM expenses WHERE user_id = ? ORDER BY {sort_by} {order_dir}', (user_id,)).fetchall()
            return [dict(row) for row in rows]

    def get_by_id(self, expense_id: str, user_id: int) -> dict | None:
        with get_db() as conn:
            row = conn.execute('SELECT * FROM expenses WHERE id = ? AND user_id = ?', (expense_id, user_id)).fetchone()
            return dict(row) if row else None

    def get_monthly_summary(self, user_id: int) -> list:
        with get_db() as conn:
            rows = conn.execute('''
                SELECT 
                    CAST(strftime('%Y', date) AS INTEGER) as year,
                    CAST(strftime('%m', date) AS INTEGER) as month,
                    type,
                    SUM(amount) as total
                FROM expenses
                WHERE user_id = ?
                GROUP BY year, month, type
                ORDER BY year, month
            ''', (user_id,)).fetchall()
            return [{"year": r["year"], "month": r["month"], "type": r["type"], "total": r["total"]} for r in rows]

    def get_category_summary(self, user_id: int) -> list:
        with get_db() as conn:
            rows = conn.execute('''
                SELECT category, type, SUM(amount) as total
                FROM expenses
                WHERE user_id = ?
                GROUP BY category, type
                ORDER BY total DESC
            ''', (user_id,)).fetchall()
            return [{"category": r["category"], "type": r["type"], "total": r["total"]} for r in rows]

    def update(self, expense_id: str, user_id: int, data: dict) -> bool:
        update_fields = []
        values = []
        for key in ["title", "amount", "category", "date", "note", "type", "account_id", "to_account_id"]:
            if key in data:
                update_fields.append(f"{key} = ?")
                if key == "amount":
                    val = float(data[key])
                elif key in ["account_id", "to_account_id"]:
                    val = int(data[key])
                else:
                    val = data[key]
                values.append(val)

        if not update_fields: return False

        values.extend([expense_id, user_id])
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                UPDATE expenses SET {', '.join(update_fields)} WHERE id = ? AND user_id = ?
            ''', values)
            return cursor.rowcount > 0

    def delete(self, expense_id: str, user_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (expense_id, user_id))
            return cursor.rowcount > 0