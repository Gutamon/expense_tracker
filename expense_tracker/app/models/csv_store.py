import contextlib
import csv
import os
import threading
import time

from flask import g, has_request_context

INT_FIELDS = {
    "expenses.csv": {"id", "category_id", "account_id", "to_account_id", "stock_transaction_id", "loan_id", "loan_payment_id"},
    "categories.csv": {"id", "is_asset", "in_budget", "sort_order"},
    "category_groups.csv": {"id", "sort_order"},
    "accounts.csv": {"id", "sort_order", "is_asset", "billing_start_day", "payment_due_day"},
    "stocks.csv": {"id", "shares", "account_id", "linked_account_id"},
    "stock_transactions.csv": {"id", "stock_id", "shares"},
    "loans.csv": {"id", "account_id", "linked_account_id"},
    "loan_payments.csv": {"id", "loan_id"},
    "monthly_budgets.csv": {"id", "year", "month"},
    "cat_monthly_budgets.csv": {"id", "category_id", "year", "month"},
    "group_monthly_budgets.csv": {"id", "group_id", "year", "month"},
    "monthly_history.csv": {"id", "category_id", "year", "month"},
    "settings.csv": set(),
}

FLOAT_FIELDS = {
    "expenses.csv": {"amount", "to_amount"},
    "categories.csv": {"monthly_budget"},
    "category_groups.csv": set(),
    "accounts.csv": {"credit_limit", "min_payment_pct", "min_payment_floor", "apr", "opening_balance"},
    "stocks.csv": {"avg_price", "current_price"},
    "stock_transactions.csv": {"price", "fee"},
    "loans.csv": {"principal", "remaining", "interest_rate"},
    "loan_payments.csv": {"amount"},
    "monthly_budgets.csv": {"amount"},
    "cat_monthly_budgets.csv": {"amount"},
    "group_monthly_budgets.csv": {"amount"},
    "monthly_history.csv": {"amount"},
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
    "expenses.csv": ["id", "title", "amount", "category", "category_id", "date", "note", "created_at",
                     "type", "account_id", "to_account_id", "to_amount",
                     "stock_transaction_id", "loan_id", "loan_payment_id"],
    "categories.csv": ["id", "name", "type", "is_asset", "in_budget", "group_name",
                       "sort_order", "monthly_budget"],
    "category_groups.csv": ["id", "name", "sort_order", "type"],
    "accounts.csv": ["id", "name", "icon", "sort_order", "type", "sub_type", "is_asset",
                     "billing_start_day", "currency", "credit_limit",
                     "payment_due_day", "min_payment_pct", "min_payment_floor", "apr", "opening_balance"],
    "stocks.csv": ["id", "symbol", "name", "shares", "avg_price", "current_price",
                   "updated_at", "account_id", "linked_account_id"],
    "stock_transactions.csv": ["id", "stock_id", "type", "date", "shares", "price",
                                "fee", "note", "created_at"],
    "loans.csv": ["id", "name", "type", "principal", "remaining", "interest_rate",
                  "start_date", "due_date", "account_id", "linked_account_id", "status", "note", "created_at"],
    "loan_payments.csv": ["id", "loan_id", "amount", "date", "note", "created_at"],
    "monthly_budgets.csv": ["id", "year", "month", "amount"],
    "cat_monthly_budgets.csv": ["id", "category_id", "year", "month", "amount"],
    "group_monthly_budgets.csv": ["id", "group_id", "year", "month", "amount"],
    "monthly_history.csv": ["id", "year", "month", "category", "category_id", "type", "amount"],
    "settings.csv": ["key", "value"],
}

_DATA_DIR = None  # root data dir (parent of the per-device users/ folder)


def set_data_dir(path: str):
    """Set the root data directory. Per-device folders live beneath it."""
    global _DATA_DIR
    _DATA_DIR = path


def root_dir() -> str:
    """Return the root data directory (holds the users/ folder)."""
    if _DATA_DIR:
        return _DATA_DIR
    return os.path.join(os.path.dirname(__file__), "..", "data")


_local = threading.local()


@contextlib.contextmanager
def use_data_dir(path: str):
    """Temporarily target a specific device folder from outside a request context.

    For background jobs (e.g. the daily FX-rate refresh) that must write into every
    device's own settings.csv without a request to bind flask.g.data_dir to any one
    of them. Thread-local so it's safe if a job ever runs in its own thread.
    """
    prev = getattr(_local, "data_dir", None)
    _local.data_dir = path
    try:
        yield
    finally:
        _local.data_dir = prev


def _data_dir() -> str:
    """Resolve the active data directory.

    During a request this is the current device's folder (bound to flask.g by the
    before_request hook). Outside a request context, an explicit use_data_dir()
    override takes precedence (background jobs); otherwise it falls back to the root.
    """
    if has_request_context():
        d = getattr(g, "data_dir", None)
        if d:
            return d
    override = getattr(_local, "data_dir", None)
    if override:
        return override
    return root_dir()


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
    # Windows 上防毒/索引程式偶爾會短暫鎖住檔案，讓 os.replace 拋 PermissionError；
    # 短暫重試即可，避免批次寫入（如匯入多筆倉位）中途失敗。
    for attempt in range(5):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1)


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
    if get_setting("onboarded") == "true":
        return False
    return len(read_csv("accounts.csv")) == 0


def _migrate_opening_balance():
    """Convert legacy 期初餘額 expense rows to account opening_balance field."""
    exp_rows = read_csv("expenses.csv")
    ob_rows = [e for e in exp_rows if e.get("category") == "期初餘額"]
    if not ob_rows:
        return
    acc_rows = read_csv("accounts.csv")
    acc_map = {str(r["id"]): r for r in acc_rows}
    for e in ob_rows:
        acc_id = str(e.get("account_id", 0))
        amount = float(e.get("amount") or 0)
        signed = amount if e.get("type") == "income" else -amount
        if acc_id in acc_map:
            acc_map[acc_id]["opening_balance"] = float(acc_map[acc_id].get("opening_balance") or 0) + signed
    write_csv("accounts.csv", acc_rows, SCHEMA["accounts.csv"])
    remaining = [e for e in exp_rows if e.get("category") != "期初餘額"]
    write_csv("expenses.csv", remaining, SCHEMA["expenses.csv"])


def _category_lookup(cat_rows: list) -> dict:
    """Map (name, type) -> id and name -> id (fallback) for backfilling category_id.
    The (name, type) key is what disambiguates a 收入「匯入」from a 支出「匯入」."""
    by_name_type = {}
    by_name = {}
    for c in cat_rows:
        cid = int(c.get("id") or 0)
        if not cid:
            continue
        name = c.get("name") or ""
        ctype = c.get("type") or ""
        by_name_type[(name, ctype)] = cid
        by_name.setdefault(name, cid)  # first-seen wins for the loose fallback
    return {"name_type": by_name_type, "name": by_name}


def _resolve_cat_id(name: str, ctype: str, lookup: dict) -> int:
    """Best-effort name(+type) -> category id. Returns 0 if unknown."""
    return lookup["name_type"].get((name, ctype)) or lookup["name"].get(name, 0)


def _migrate_category_id():
    """Backfill expenses / monthly_history.category_id from the stored category name.

    Once populated, category_id is the source of truth for identity (filters) and
    display name is resolved live — so renaming a category在設定頁 reflects everywhere,
    and 同名不同型別的類別（收入/支出「匯入」）不再被混為一談。 Idempotent: rows that already
    carry a category_id are left untouched; rows whose name maps to nothing stay 0.
    """
    cat_rows = read_csv("categories.csv")
    if not cat_rows:
        return
    lookup = _category_lookup(cat_rows)

    exp_rows = read_csv("expenses.csv")
    changed = False
    for e in exp_rows:
        if int(e.get("category_id") or 0):
            continue
        if e.get("type") == "transfer":
            continue
        cid = _resolve_cat_id(e.get("category") or "", e.get("type") or "", lookup)
        if cid:
            e["category_id"] = cid
            changed = True
    if changed:
        write_csv("expenses.csv", exp_rows, SCHEMA["expenses.csv"])

    hist_rows = read_csv("monthly_history.csv")
    changed = False
    for h in hist_rows:
        if int(h.get("category_id") or 0):
            continue
        cid = _resolve_cat_id(h.get("category") or "", h.get("type") or "", lookup)
        if cid:
            h["category_id"] = cid
            changed = True
    if changed:
        write_csv("monthly_history.csv", hist_rows, SCHEMA["monthly_history.csv"])


def ensure_category_id_migrated():
    """Run _migrate_category_id once per device, gated by a settings flag.

    Called from the before_request hook for pre-existing device folders (new devices
    are migrated by init_current_user). The flag check is a cheap settings read; the
    expensive CSV rewrite only happens the first time."""
    if get_setting("cat_id_migrated") == "true":
        return
    _migrate_category_id()
    set_setting("cat_id_migrated", "true")


def _init_dir(path: str):
    """Create a data directory and seed any missing CSV files (header only)."""
    os.makedirs(path, exist_ok=True)
    for filename, fieldnames in SCHEMA.items():
        p = os.path.join(path, filename)
        if not os.path.exists(p):
            with open(p, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()


def init_current_user():
    """Seed the current device's folder and run one-time migrations.

    Runs against the active data dir (bound to flask.g during a request), so it must
    be called after g.data_dir is set. Invoked once when a device folder is created.
    """
    _init_dir(_data_dir())
    _migrate_opening_balance()
    _migrate_category_id()
    set_setting("cat_id_migrated", "true")


def init_data_dir():
    """Ensure the root data dir and its users/ subfolder exist.

    Called at startup. Data is per-device, so this does not seed the CSV files at the
    root — per-device seeding happens via init_current_user().
    """
    from config import Config
    os.makedirs(os.path.join(root_dir(), Config.USERS_SUBDIR), exist_ok=True)
