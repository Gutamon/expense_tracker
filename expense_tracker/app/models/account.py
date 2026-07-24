from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA, seed_if_empty


class AccountModel:
    DEFAULT_ACCOUNTS = [
        {"name": "現金",   "icon": "💵", "type": "asset",     "sub_type": "現金",    "is_asset": 1},
        {"name": "銀行",   "icon": "🏦", "type": "asset",     "sub_type": "銀行",    "is_asset": 1},
        {"name": "預付儲值", "icon": "🪙", "type": "asset",   "sub_type": "預付儲值", "is_asset": 1},
        {"name": "其他",   "icon": "👝", "type": "asset",     "sub_type": "其他",    "is_asset": 1},
    ]

    def _build_defaults(self):
        return [{
            "id": i + 1,
            "name": a["name"],
            "icon": a["icon"],
            "sort_order": i,
            "type": a["type"],
            "sub_type": a.get("sub_type", ""),
            "is_asset": a.get("is_asset", 1),
            "billing_start_day": 1,
            "currency": "TWD",
            "credit_limit": 0,
            "payment_due_day": 0,
            "min_payment_pct": 10,
            "min_payment_floor": 1000,
            "apr": 0,
        } for i, a in enumerate(self.DEFAULT_ACCOUNTS)]

    def ensure_defaults(self):
        # Atomic seed-if-empty: the shell's concurrent iframe requests all call this on
        # a first-touch device; without serialization they raced and 500'd (see
        # csv_store.seed_if_empty).
        seed_if_empty("accounts.csv", self._build_defaults)

    def get_all(self) -> list:
        self.ensure_defaults()
        rows = read_csv("accounts.csv")
        rows.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
        return rows

    def compute_balances(self, accounts: list = None) -> dict:
        """Return {account_id: balance} in each account's own currency.

        Seeds from opening_balance, then applies every expense/income/transfer.
        Mirrors the balance logic on the home page and is reused by balance
        correction so the two never drift.
        """
        if accounts is None:
            accounts = self.get_all()
        balances = {}
        for a in accounts:
            balances[a["id"]] = float(a.get("opening_balance") or 0)
        for e in read_csv("expenses.csv"):
            acc_id = e.get("account_id")
            to_acc_id = e.get("to_account_id")
            if acc_id not in balances:
                balances[acc_id] = 0.0
            t = e.get("type")
            amt = float(e.get("amount") or 0)
            if t == "income":
                balances[acc_id] += amt
            elif t == "expense":
                balances[acc_id] -= amt
            elif t == "transfer":
                balances[acc_id] -= amt
                if to_acc_id not in balances:
                    balances[to_acc_id] = 0.0
                balances[to_acc_id] += float(e.get("to_amount") or amt)
        return balances

    def adjust_opening_balance(self, account_id: str, target_balance: float):
        """Nudge an account's opening_balance so its computed balance == target.

        Used by the correction flow. The adjustment lands in opening_balance, so it
        is never counted as income/expense. Returns the delta applied, or None if
        the account is missing.
        """
        account_id = str(account_id)
        rows = read_csv("accounts.csv")
        target = next((r for r in rows if str(r.get("id")) == account_id), None)
        if not target:
            return None
        current = self.compute_balances(rows).get(target["id"], 0.0)
        delta = float(target_balance) - float(current)
        target["opening_balance"] = float(target.get("opening_balance") or 0) + delta
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
        return delta

    def create(self, name: str, icon: str = "💰", type: str = "asset", sub_type: str = "",
               is_asset: int = 1, billing_start_day: int = 1, currency: str = "TWD",
               credit_limit: float = 0, payment_due_day: int = 0, min_payment_pct: float = 10,
               min_payment_floor: float = 1000, apr: float = 0, opening_balance: float = 0) -> str:
        rows = read_csv("accounts.csv")
        new_id = next_id(rows)
        rows.append({
            "id": new_id,
            "name": name,
            "icon": icon,
            "sort_order": 0,
            "type": type,
            "sub_type": sub_type,
            "is_asset": int(is_asset),
            "billing_start_day": billing_start_day,
            "currency": currency,
            "credit_limit": credit_limit,
            "payment_due_day": payment_due_day,
            "min_payment_pct": min_payment_pct,
            "min_payment_floor": min_payment_floor,
            "apr": apr,
            "opening_balance": opening_balance,
        })
        write_csv("accounts.csv", rows, SCHEMA["accounts.csv"])
        return str(new_id)

    def update(self, account_id: str, data: dict) -> bool:
        rows = read_csv("accounts.csv")
        account_id = str(account_id)
        for r in rows:
            if str(r.get("id")) == account_id:
                for key in ["name", "icon", "type", "sub_type", "is_asset", "billing_start_day", "currency",
                            "credit_limit", "payment_due_day", "min_payment_pct", "min_payment_floor", "apr"]:
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
