from app.models.db import get_db

class AccountModel:
    DEFAULT_ACCOUNTS = [
        {"name": "現金", "icon": "💵", "type": "asset", "is_asset": 1},
        {"name": "銀行", "icon": "🏦", "type": "asset", "is_asset": 1},
        {"name": "儲值支付", "icon": "🪙", "type": "asset", "is_asset": 1},
        {"name": "信用卡", "icon": "💳", "type": "liability", "is_asset": 1},
        {"name": "其他", "icon": "👝", "type": "asset", "is_asset": 1},
    ]

    def ensure_defaults(self, user_id: int):
        with get_db() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM accounts WHERE user_id = ?", (user_id,)).fetchone()["c"]
            if count == 0:
                for a in self.DEFAULT_ACCOUNTS:
                    conn.execute("INSERT INTO accounts (user_id, name, icon, type, sort_order, is_asset) VALUES (?, ?, ?, ?, 0, ?)", (user_id, a["name"], a["icon"], a["type"], a.get("is_asset", 1)))

    def get_by_user(self, user_id: int) -> list:
        self.ensure_defaults(user_id)
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY sort_order, id", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def create(self, user_id: int, name: str, icon: str = "💰", type: str = "asset", is_asset: int = 1) -> str:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO accounts (user_id, name, icon, type, sort_order, is_asset) VALUES (?, ?, ?, ?, 0, ?)", (user_id, name, icon, type, is_asset))
            return str(cursor.lastrowid)

    def update(self, account_id: str, user_id: int, data: dict) -> bool:
        fields, values = [], []
        for key in ["name", "icon", "type", "is_asset"]:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if not fields:
            return False
        values.extend([account_id, user_id])
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ? AND user_id = ?", values)
            return cursor.rowcount > 0

    def update_sort_orders(self, user_id: int, id_order_list: list) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            for order, item_id in enumerate(id_order_list):
                cursor.execute("UPDATE accounts SET sort_order = ? WHERE id = ? AND user_id = ?", (order, item_id, user_id))
            return True

    def delete(self, account_id: str, user_id: int, replace_with_id: str = None) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            if replace_with_id:
                cursor.execute("UPDATE expenses SET account_id = ? WHERE account_id = ? AND user_id = ?", (replace_with_id, account_id, user_id))
                cursor.execute("UPDATE expenses SET to_account_id = ? WHERE to_account_id = ? AND user_id = ?", (replace_with_id, account_id, user_id))
            cursor.execute("DELETE FROM accounts WHERE id = ? AND user_id = ?", (account_id, user_id))
            return cursor.rowcount > 0
