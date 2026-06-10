import csv
import os
import zipfile
import tempfile
from datetime import datetime
from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA

DATE_FORMATS = ["%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y",
                "%Y.%m.%d", "%Y%m%d"]

FIELD_HINTS = {
    "date":     ["日期", "date", "交易日期", "time", "時間"],
    "amount":   ["金額", "amount", "數量", "price", "費用"],
    "type":     ["類型", "type", "收支", "收支類型", "交易類型", "方向"],
    "title":    ["標題", "摘要", "說明", "description", "title", "名稱"],
    "category": ["類別", "category", "分類", "子類別"],
    "account":  ["帳戶", "account", "帳戶1", "帳戶名稱"],
    "note":     ["備注", "備註", "note", "remark", "附言"],
    "currency": ["幣別", "currency", "貨幣", "幣種"],
}

# Values that clearly indicate a type column
_TYPE_VALUE_HINTS = frozenset({
    "支出", "收入", "轉帳", "轉入", "轉出",
    "expense", "income", "transfer", "debit", "credit",
})


def _parse_date(value: str) -> str:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def _parse_amount(value: str) -> float:
    value = str(value).strip().replace(",", "").replace("$", "").replace("NT", "").replace("TWD", "").strip()
    try:
        return abs(float(value))
    except ValueError:
        return 0.0


def _detect_delimiter(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        return dialect.delimiter
    except csv.Error:
        return ","


# Substrings in category/title that strongly signal income
_INCOME_HINTS = frozenset({
    "薪水", "工資", "獎金", "股息", "利息", "存款利息",
    "退款", "退費", "回饋", "現金回饋", "紅利", "返現",
    "他人還款", "理賠", "補助", "津貼", "天下掉下來",
    "股票盈利", "盈利", "獲利", "入帳",
    "salary", "bonus", "dividend", "interest", "refund", "cashback",
})


def _resolve_type(raw_type: str, type_mapping: dict,
                  raw_category: str = "", raw_title: str = "",
                  raw_note: str = "", raw_amount: str = "") -> str:
    """Determine expense/income/transfer using all available row context."""
    # 1. Explicit user type_mapping
    mapped = type_mapping.get(raw_type, "").lower()
    if mapped in ("expense", "income", "transfer"):
        return mapped

    # 2. Recognise common type-column values directly
    if raw_type:
        t = raw_type.lower()
        if "收入" in t or t in ("income", "credit", "in"):
            return "income"
        if "轉" in t or t in ("transfer",):
            return "transfer"
        if "支出" in t or "費用" in t or t in ("expense", "debit", "out"):
            return "expense"

    # 3. Income keywords in category or title/note
    combined = raw_category + " " + raw_title + " " + raw_note
    if any(hint in combined for hint in _INCOME_HINTS):
        return "income"

    # 4. Negative sign in raw amount (bank-statement format: negative = debit)
    if raw_amount:
        try:
            v = float(str(raw_amount).replace(",", "").replace("$", "")
                      .replace("NT", "").replace("TWD", "").strip())
            if v < 0:
                return "expense"
        except ValueError:
            pass

    return "expense"


def _guess_mapping(columns: list, column_values: dict = None) -> dict:
    mapping = {}
    lower_cols = {c.lower(): c for c in columns}
    for field, hints in FIELD_HINTS.items():
        for hint in hints:
            if hint.lower() in lower_cols:
                mapping[field] = lower_cols[hint.lower()]
                break
    # If type column not found by name, detect by values
    if "type" not in mapping and column_values:
        for col in columns:
            vals = [v for v in column_values.get(col, []) if v]
            if vals and all(v in _TYPE_VALUE_HINTS for v in vals):
                mapping["type"] = col
                break
    return mapping


def _read_rows(file_path: str):
    """Return (header, rows_iter) with auto-detected delimiter."""
    delimiter = _detect_delimiter(file_path)
    f = open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.reader(f, delimiter=delimiter)
    header = next(reader, None)
    if not header:
        f.close()
        return [], iter([]), f
    header = [c.strip() for c in header]
    return header, reader, f


def extract_from_zip(zip_path: str) -> str:
    """Extract the first usable CSV/TXT from a ZIP into a temp file. Returns temp path."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        target = None
        for name in names:
            basename = os.path.basename(name)
            lower = basename.lower()
            if (lower.endswith(".csv") or lower.endswith(".txt")) and basename not in SCHEMA:
                target = name
                break
        if target is None:
            for name in names:
                lower = os.path.basename(name).lower()
                if lower.endswith(".csv") or lower.endswith(".txt"):
                    target = name
                    break
        if target is None:
            raise ValueError("ZIP 中找不到 CSV 或文字檔")

        suffix = ".csv" if target.lower().endswith(".csv") else ".txt"
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.close(tmp_fd)
            with zf.open(target) as src, open(tmp_path, "wb") as dst:
                dst.write(src.read())
        except Exception:
            os.unlink(tmp_path)
            raise
        return tmp_path


def preview_file(file_path: str) -> dict:
    delimiter = _detect_delimiter(file_path)
    preview_rows = []
    columns = []
    column_values: dict = {}
    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return {"columns": [], "preview": [], "suggested_mapping": {}, "column_values": {}}
        columns = [c.strip() for c in header]
        column_values = {c: [] for c in columns}
        _seen: dict = {c: set() for c in columns}
        for i, row in enumerate(reader):
            row_dict = {columns[j]: row[j].strip() if j < len(row) else "" for j in range(len(columns))}
            if i < 5:
                preview_rows.append(row_dict)
            for c in columns:
                val = row_dict.get(c, "")
                if val and val not in _seen[c]:
                    _seen[c].add(val)
                    column_values[c].append(val)
    return {
        "columns": columns,
        "preview": preview_rows,
        "suggested_mapping": _guess_mapping(columns, column_values),
        "column_values": column_values,
    }


# Keep old name as alias
preview_csv = preview_file


def analyze_import(file_path: str, mapping: dict, type_mapping: dict = None) -> dict:
    """Dry-run: return new categories and accounts that would be created, without writing."""
    if type_mapping is None:
        type_mapping = {}

    delimiter = _detect_delimiter(file_path)
    existing_cats = {r["name"] for r in read_csv("categories.csv")}
    existing_accs = {r["name"] for r in read_csv("accounts.csv")}

    new_cats = {}   # name -> guessed type
    new_accs = {}   # name -> guessed currency
    total = 0

    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return {"total": 0, "new_categories": [], "new_accounts": []}
        header = [c.strip() for c in header]

        for raw_row in reader:
            if not any(cell.strip() for cell in raw_row):
                continue
            total += 1
            row = {header[j]: raw_row[j].strip() if j < len(raw_row) else "" for j in range(len(header))}

            raw_type  = row.get(mapping.get("type",     ""), "").strip()
            raw_cat   = row.get(mapping.get("category", ""), "").strip()
            raw_title = row.get(mapping.get("title",    ""), "").strip()
            raw_note  = row.get(mapping.get("note",     ""), "").strip()
            raw_amt   = row.get(mapping.get("amount",   ""), "0").strip()
            mapped_type = _resolve_type(raw_type, type_mapping, raw_cat, raw_title, raw_note, raw_amt)

            if raw_cat and raw_cat not in existing_cats and raw_cat not in new_cats:
                new_cats[raw_cat] = mapped_type

            raw_acc = row.get(mapping.get("account", ""), "").strip()
            if raw_acc and raw_acc not in existing_accs and raw_acc not in new_accs:
                raw_cur = row.get(mapping.get("currency", ""), "").strip() or "TWD"
                new_accs[raw_acc] = raw_cur

    return {
        "total": total,
        "new_categories": [{"name": k, "type": v} for k, v in new_cats.items()],
        "new_accounts":   [{"name": k, "currency": v} for k, v in new_accs.items()],
    }


def import_csv(file_path: str, mapping: dict, type_mapping: dict = None,
               account_currencies: dict = None, account_types: dict = None,
               category_type_overrides: dict = None) -> dict:
    """
    mapping: {field: csv_column}
    type_mapping: {csv_type_value: "expense"/"income"/"transfer"}
    account_currencies: {account_name: currency} for new accounts
    account_types: {account_name: "asset"/"liability"} for new accounts
    category_type_overrides: {category_name: "expense"/"income"/"transfer"} user overrides
    """
    if type_mapping is None:
        type_mapping = {}
    if account_currencies is None:
        account_currencies = {}
    if account_types is None:
        account_types = {}
    if category_type_overrides is None:
        category_type_overrides = {}

    delimiter = _detect_delimiter(file_path)

    existing_expenses = read_csv("expenses.csv")

    categories_rows = read_csv("categories.csv")
    known_cats = {r["name"]: r for r in categories_rows}
    new_cats = {}

    accounts_rows = read_csv("accounts.csv")
    known_accs = {r["name"]: r for r in accounts_rows}
    new_accs = {}

    imported = 0
    errors = []
    new_expenses = []

    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return {"imported": 0, "errors": ["檔案沒有標頭列"]}
        header = [c.strip() for c in header]

        for i, raw_row in enumerate(reader):
            if not any(cell.strip() for cell in raw_row):
                continue  # skip blank lines
            try:
                row = {header[j]: raw_row[j].strip() if j < len(raw_row) else "" for j in range(len(header))}

                raw_date     = row.get(mapping.get("date",     ""), "").strip()
                raw_amount   = row.get(mapping.get("amount",   ""), "0").strip()
                raw_type     = row.get(mapping.get("type",     ""), "").strip()
                raw_title    = row.get(mapping.get("title",    ""), "").strip()
                raw_category = row.get(mapping.get("category", ""), "").strip()
                raw_account  = row.get(mapping.get("account",  ""), "").strip()
                raw_note     = row.get(mapping.get("note",     ""), "").strip()

                date   = _parse_date(raw_date) if raw_date else datetime.now().strftime("%Y-%m-%d")
                amount = _parse_amount(raw_amount)
                if amount == 0:
                    continue  # skip genuinely empty/zero-amount rows

                mapped_type = _resolve_type(raw_type, type_mapping,
                                           raw_category, raw_title, raw_note, raw_amount)

                title    = raw_title or raw_note or raw_category or "匯入"
                note     = raw_note if raw_note != title else ""
                category = raw_category or "未分類"

                # Auto-create missing category
                if category not in known_cats and category not in new_cats:
                    new_cats[category] = {
                        "id": next_id(categories_rows) + len(new_cats),
                        "name": category,
                        "type": category_type_overrides.get(category, mapped_type),
                        "is_asset": 1,
                        "in_budget": 1,
                        "group_name": "匯入",
                        "sort_order": 99,
                        "monthly_budget": 0,
                    }

                # Resolve / auto-create account
                account_id = 0
                if raw_account:
                    if raw_account in known_accs:
                        account_id = int(known_accs[raw_account]["id"])
                    elif raw_account in new_accs:
                        account_id = new_accs[raw_account]["id"]
                    else:
                        currency = account_currencies.get(raw_account, "TWD")
                        acc_type = account_types.get(raw_account, "asset")
                        new_acc_id = next_id(accounts_rows) + len(new_accs)
                        new_accs[raw_account] = {
                            "id": new_acc_id,
                            "name": raw_account,
                            "icon": "💰",
                            "sort_order": 90 + len(new_accs),
                            "type": acc_type,
                            "is_asset": 1,
                            "billing_start_day": 1,
                            "currency": currency,
                            "credit_limit": 0,
                        }
                        account_id = new_acc_id

                new_id_val = next_id(existing_expenses) + len(new_expenses)
                new_expenses.append({
                    "id": new_id_val,
                    "title": title,
                    "amount": amount,
                    "category": category,
                    "date": date,
                    "note": note,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "type": mapped_type,
                    "account_id": account_id,
                    "to_account_id": 0,
                    "to_amount": "",
                    "stock_transaction_id": "",
                    "loan_id": "",
                    "loan_payment_id": "",
                })
                imported += 1
            except Exception as e:
                errors.append(f"第 {i+2} 行：{str(e)}")

    # Save new categories
    if new_cats:
        grp_rows = read_csv("category_groups.csv")
        if not any(r.get("name") == "匯入" for r in grp_rows):
            grp_rows.append({"id": next_id(grp_rows), "name": "匯入", "sort_order": 99, "type": "expense"})
            write_csv("category_groups.csv", grp_rows, SCHEMA["category_groups.csv"])
        for cat in new_cats.values():
            categories_rows.append(cat)
        write_csv("categories.csv", categories_rows, SCHEMA["categories.csv"])

    # Save new accounts
    if new_accs:
        for acc in new_accs.values():
            accounts_rows.append(acc)
        write_csv("accounts.csv", accounts_rows, SCHEMA["accounts.csv"])

    # Save new expenses
    if new_expenses:
        write_csv("expenses.csv", existing_expenses + new_expenses, SCHEMA["expenses.csv"])

    if imported > 0:
        _clean_defaults_after_import()

    return {"imported": imported, "errors": errors}


def _clean_defaults_after_import():
    """Delete default categories/groups/accounts that are unused after an import."""
    DEFAULT_CATEGORY_NAMES = {"餐飲", "交通", "娛樂", "購物", "醫療", "住宿", "教育", "薪水", "獎金", "其他"}
    DEFAULT_GROUP_NAMES    = {"生活", "休閒", "健康", "學習", "主要收入", "額外收入", "其他"}
    DEFAULT_ACCOUNT_NAMES  = {"現金", "銀行", "儲值支付", "信用卡", "其他"}

    expenses  = read_csv("expenses.csv")
    used_cats = {e.get("category", "") for e in expenses}
    used_acc_ids = (
        {str(e.get("account_id", "")) for e in expenses} |
        {str(e.get("to_account_id", "")) for e in expenses}
    )

    # Remove unused default categories
    cats = read_csv("categories.csv")
    cats_after = [c for c in cats if c["name"] not in DEFAULT_CATEGORY_NAMES or c["name"] in used_cats]
    if len(cats_after) != len(cats):
        write_csv("categories.csv", cats_after, SCHEMA["categories.csv"])

    # Remove default groups that have no remaining categories
    remaining_groups = {c.get("group_name", "") for c in cats_after}
    groups = read_csv("category_groups.csv")
    groups_after = [g for g in groups if g["name"] not in DEFAULT_GROUP_NAMES or g["name"] in remaining_groups]
    if len(groups_after) != len(groups):
        write_csv("category_groups.csv", groups_after, SCHEMA["category_groups.csv"])

    # Remove unused default accounts
    accs = read_csv("accounts.csv")
    accs_after = [a for a in accs if a["name"] not in DEFAULT_ACCOUNT_NAMES or str(a["id"]) in used_acc_ids]
    if len(accs_after) != len(accs):
        write_csv("accounts.csv", accs_after, SCHEMA["accounts.csv"])
