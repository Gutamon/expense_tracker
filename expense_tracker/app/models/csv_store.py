import csv
import os

INT_FIELDS = {
    "expenses.csv": {"id", "account_id", "to_account_id", "stock_transaction_id", "loan_id", "loan_payment_id"},
    "categories.csv": {"id", "is_asset", "in_budget", "sort_order"},
    "category_groups.csv": {"id", "sort_order"},
    "accounts.csv": {"id", "sort_order", "is_asset", "billing_start_day"},
    "stocks.csv": {"id", "shares", "account_id"},
    "stock_transactions.csv": {"id", "stock_id", "shares"},
    "loans.csv": {"id", "account_id"},
    "loan_payments.csv": {"id", "loan_id"},
    "monthly_budgets.csv": {"id", "year", "month"},
    "cat_monthly_budgets.csv": {"id", "category_id", "year", "month"},
    "settings.csv": set(),
}

FLOAT_FIELDS = {
    "expenses.csv": {"amount", "to_amount"},
    "categories.csv": {"monthly_budget"},
    "category_groups.csv": set(),
    "accounts.csv": {"credit_limit"},
    "stocks.csv": {"avg_price", "current_price"},
    "stock_transactions.csv": {"price", "fee"},
    "loans.csv": {"principal", "remaining", "interest_rate"},
    "loan_payments.csv": {"amount"},
    "monthly_budgets.csv": {"amount"},
    "cat_monthly_budgets.csv": {"amount"},
    "settings.csv": set(),
}


def coerce_row(filename: str, row: dict) -> dict:
    int_f = INT_FIELDS.get(filename, set())
    float_f = FLOAT_FIELDS.get(filename, set())
    for k, v in row.items():
        if k in int_f:
            try:
                row[k] = int(v) if v not in (None, "") else 0
            except (ValueError, TypeError):
                row[k] = 0
        elif k in float_f:
            try:
                row[k] = float(v) if v not in (None, "") else 0.0
            except (ValueError, TypeError):
                row[k] = 0.0
    return row


SCHEMA = {
    "expenses.csv": ["id", "title", "amount", "category", "date", "note", "created_at",
                     "type", "account_id", "to_account_id", "to_amount",
                     "stock_transaction_id", "loan_id", "loan_payment_id"],
    "categories.csv": ["id", "name", "type", "is_asset", "in_budget", "group_name",
                       "sort_order", "monthly_budget"],
    "category_groups.csv": ["id", "name", "sort_order", "type"],
    "accounts.csv": ["id", "name", "icon", "sort_order", "type", "is_asset",
                     "billing_start_day", "currency", "credit_limit"],
    "stocks.csv": ["id", "symbol", "name", "shares", "avg_price", "current_price",
                   "updated_at", "account_id"],
    "stock_transactions.csv": ["id", "stock_id", "type", "date", "shares", "price",
                                "fee", "note", "created_at"],
    "loans.csv": ["id", "name", "type", "principal", "remaining", "interest_rate",
                  "start_date", "due_date", "account_id", "status", "note", "created_at"],
    "loan_payments.csv": ["id", "loan_id", "amount", "date", "note", "created_at"],
    "monthly_budgets.csv": ["id", "year", "month", "amount"],
    "cat_monthly_budgets.csv": ["id", "category_id", "year", "month", "amount"],
    "settings.csv": ["key", "value"],
}

_DATA_DIR = None


def set_data_dir(path: str):
    global _DATA_DIR
    _DATA_DIR = path


def _data_dir() -> str:
    if _DATA_DIR:
        return _DATA_DIR
    return os.path.join(os.path.dirname(__file__), "..", "data")


def _path(filename: str) -> str:
    return os.path.join(_data_dir(), filename)


def read_csv(filename: str) -> list:
    p = _path(filename)
    if not os.path.exists(p):
        return []
    rows = []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(coerce_row(filename, dict(row)))
    return rows


def write_csv(filename: str, rows: list, fieldnames: list):
    p = _path(filename)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    os.replace(tmp, p)


def next_id(rows: list) -> int:
    if not rows:
        return 1
    return max(int(r.get("id", 0) or 0) for r in rows) + 1


def get_setting(key: str, default=None):
    rows = read_csv("settings.csv")
    for r in rows:
        if r.get("key") == key:
            return r.get("value", default)
    return default


def set_setting(key: str, value):
    rows = read_csv("settings.csv")
    found = False
    for r in rows:
        if r.get("key") == key:
            r["value"] = str(value)
            found = True
            break
    if not found:
        rows.append({"key": key, "value": str(value)})
    write_csv("settings.csv", rows, SCHEMA["settings.csv"])


def is_first_run() -> bool:
    rows = read_csv("accounts.csv")
    return len(rows) == 0


def init_data_dir():
    d = _data_dir()
    os.makedirs(d, exist_ok=True)
    for filename, fieldnames in SCHEMA.items():
        p = os.path.join(d, filename)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
