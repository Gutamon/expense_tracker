from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA


class AccountModel:
    DEFAULT_ACCOUNTS = [
        {"name": "現金",   "icon": "💵", "type": "asset",     "is_asset": 1},
        {"name": "銀行",   "icon": "🏦", "type": "asset",     "is_asset": 1},
        {"name": "儲值支付", "icon": "🪙", "type": "asset",   "is_asset": 1},
        {"name": "信用卡", "icon": "💳", "type": "liability",  "is_asset": 1},
        {"name": "其他",   "icon": "👝", "type": "asset",     "is_asset": 1},
    ]

    def ensure_defaults(self):
        rows = read_csv("accounts.csv")
        if rows:
            return
        for i, a in enumerate(self.DEFAULT_ACCOUNTS):
            rows.append({
                "id": i + 1,
                "name": a["name"],
                "icon": a["icon"],
                "sort_order": i,
                "type": a["type"],
                "is_asset": a.get("is_asset", 1),
                "billing_start_day": 1,
                "currency": "TWD",
                "credit_limit": 0,
            })
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])

    def get_all(self) -> list:
        self.ensure_defaults()
        rows = read_csv("accounts.csv")
        rows.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
        return rows

    def create(self, name: str, icon: str = "💰", type: str = "asset", is_asset: int = 1,
               billing_start_day: int = 1, currency: str = "TWD", credit_limit: float = 0) -> str:
        rows = read_csv("accounts.csv")
        new_id = next_id(rows)
        rows.append({
            "id": new_id,
            "name": name,
            "icon": icon,
            "sort_order": 0,
            "type": type,
            "is_asset": int(is_asset),
            "billing_start_day": billing_start_day,
            "currency": currency,
            "credit_limit": credit_limit,
        })
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
        return str(new_id)

    def update(self, account_id: str, data: dict) -> bool:
        rows = read_csv("accounts.csv")
        account_id = str(account_id)
        for r in rows:
            if str(r.get("id")) == account_id:
                for key in ["name", "icon", "type", "is_asset", "billing_start_day", "currency", "credit_limit"]:
                    if key in data:
                        r[key] = data[key]
                write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
                return True
        return False

    def update_sort_orders(self, id_order_list) -> bool:
        rows = read_csv("accounts.csv")
        order_map = {str(item_id): i for i, item_id in enumerate(id_order_list)}
        for r in rows:
            if str(r.get("id")) in order_map:
                r["sort_order"] = order_map[str(r["id"])]
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
        return True

    def delete(self, account_id: str, replace_with_id: str = None) -> bool:
        rows = read_csv("accounts.csv")
        account_id = str(account_id)
        if not any(str(r.get("id")) == account_id for r in rows):
            return False

        if replace_with_id:
            exp_rows = read_csv("expenses.csv")
            for e in exp_rows:
                if str(e.get("account_id")) == account_id:
                    e["account_id"] = replace_with_id
                if str(e.get("to_account_id")) == account_id:
                    e["to_account_id"] = replace_with_id
            write_csv("expenses.csv", exp_rows, SCHEMA["expenses.csv"])

        rows = [r for r in rows if str(r.get("id")) != account_id]
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
        return True
