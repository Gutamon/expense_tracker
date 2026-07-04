import csv
import json
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
    "category": ["類別", "category", "分類", "子類別"],
    "account":  ["帳戶", "account", "帳戶1", "帳戶名稱"],
}

_TYPE_VALUE_HINTS = frozenset({
    "支出", "收入", "轉帳", "轉入", "轉出",
    "expense", "income", "transfer", "debit", "credit",
})

_INCOME_HINTS = frozenset({
    "薪水", "工資", "獎金", "股息", "利息", "存款利息",
    "退款", "退費", "回饋", "現金回饋", "紅利", "返現",
    "他人還款", "理賠", "補助", "津貼",
    "股票盈利", "盈利", "獲利", "入帳",
    "salary", "bonus", "dividend", "interest", "refund", "cashback",
})

ICON_MAP = {
    "現金": "💵", "銀行": "🏦", "預付儲值": "🪙", "投資": "📈",
    "保單": "🛡️", "其他": "👝", "信用卡": "💳", "借貸": "🤝", "負債其他": "👝",
}
LIABILITY_SUBTYPES = frozenset({"信用卡", "借貸", "負債其他"})


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


def _resolve_type(raw_type: str, type_mapping: dict,
                  raw_category: str = "", raw_amount: str = "") -> str:
    mapped = type_mapping.get(raw_type, "").lower()
    if mapped in ("expense", "income", "transfer"):
        return mapped

    if raw_type:
        t = raw_type.lower()
        if "收入" in t or t in ("income", "credit", "in"):
            return "income"
        if "轉" in t or t in ("transfer",):
            return "transfer"
        if "支出" in t or "費用" in t or t in ("expense", "debit", "out"):
            return "expense"

    if any(hint in raw_category for hint in _INCOME_HINTS):
        return "income"

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
    if "type" not in mapping and column_values:
        for col in columns:
            vals = [v for v in column_values.get(col, []) if v]
            if vals and all(v in _TYPE_VALUE_HINTS for v in vals):
                mapping["type"] = col
                break
    return mapping


def ai_suggest_mapping(headers: list, sample_rows: list) -> dict | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None

    system = (
        "You are a financial data analyst. Map CSV columns to expense tracker fields: "
        "date, amount, category, account, type. "
        "Only include confident mappings. Respond ONLY with valid JSON, no markdown."
    )
    user = (
        f"CSV headers and sample rows:\n"
        f"{json.dumps({'headers': headers, 'sample_rows': sample_rows}, ensure_ascii=False)}\n\n"
        "Return JSON with:\n"
        "- \"mapping\": {field_key: exact_csv_column_name}\n"
        "- \"type_values\": {raw_value: \"expense\"|\"income\"|\"transfer\"} "
        "(empty {} if no type column)"
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        return result if isinstance(result, dict) and "mapping" in result else None
    except Exception:
        return None


def _merge_mappings(rule_based: dict, ai_result: dict | None, valid_columns: set) -> tuple:
    merged = dict(rule_based)
    type_values = {}
    if ai_result is None:
        return merged, type_values
    for field, col in ai_result.get("mapping", {}).items():
        if col in valid_columns:
            merged[field] = col
    type_values = ai_result.get("type_values", {})
    return merged, type_values


def extract_from_zip(zip_path: str) -> str:
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


preview_csv = preview_file


def analyze_settings_import(file_path: str, mapping: dict, type_mapping: dict = None) -> dict:
    """Dry-run: extract accounts, categories, and monthly summaries from CSV."""
    if type_mapping is None:
        type_mapping = {}

    delimiter = _detect_delimiter(file_path)
    existing_cats = {r["name"] for r in read_csv("categories.csv")}
    existing_accs = {r["name"] for r in read_csv("accounts.csv")}

    new_cats = {}    # name -> inferred type
    new_accs = {}    # name -> currency
    monthly_agg = {}  # (year, month, category, type) -> amount
    date_range = []

    with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return {"accounts": [], "categories": [], "monthly_summary": [], "months_count": 0}
        header = [c.strip() for c in header]

        for raw_row in reader:
            if not any(cell.strip() for cell in raw_row):
                continue
            row = {header[j]: raw_row[j].strip() if j < len(raw_row) else "" for j in range(len(header))}

            raw_date   = row.get(mapping.get("date",     ""), "").strip()
            raw_amount = row.get(mapping.get("amount",   ""), "0").strip()
            raw_type   = row.get(mapping.get("type",     ""), "").strip()
            raw_cat    = row.get(mapping.get("category", ""), "").strip()
            raw_acc    = row.get(mapping.get("account",  ""), "").strip()

            amount = _parse_amount(raw_amount)
            if amount == 0:
                continue

            mapped_type = _resolve_type(raw_type, type_mapping, raw_cat, raw_amount)

            # Skip transfers entirely — transfer accounts are not proposed as new
            if mapped_type == "transfer":
                continue

            if raw_cat and raw_cat not in existing_cats and raw_cat not in new_cats:
                new_cats[raw_cat] = mapped_type

            if raw_acc and raw_acc not in existing_accs and raw_acc not in new_accs:
                new_accs[raw_acc] = "TWD"

            if raw_date:
                date = _parse_date(raw_date)
                if len(date) >= 7:
                    try:
                        year = int(date[:4])
                        month = int(date[5:7])
                        cat_key = raw_cat or "未分類"
                        key = (year, month, cat_key, mapped_type)
                        monthly_agg[key] = monthly_agg.get(key, 0) + amount
                        date_range.append((year, month))
                    except ValueError:
                        pass

    monthly_summary = [
        {"year": k[0], "month": k[1], "category": k[2], "type": k[3], "amount": round(v, 2)}
        for k, v in sorted(monthly_agg.items())
    ]
    months_set = sorted({(k[0], k[1]) for k in monthly_agg})
    months_count = len(months_set)
    date_from = f"{months_set[0][0]}/{months_set[0][1]:02d}" if months_set else ""
    date_to   = f"{months_set[-1][0]}/{months_set[-1][1]:02d}" if months_set else ""

    return {
        "accounts":       [{"name": k, "currency": v} for k, v in new_accs.items()],
        "categories":     [{"name": k, "type": v} for k, v in new_cats.items()],
        "monthly_summary": monthly_summary,
        "months_count":   months_count,
        "date_from":      date_from,
        "date_to":        date_to,
    }


def import_settings(file_path: str, mapping: dict, type_mapping: dict,
                    accounts_config: list, categories_config: list,
                    import_history: bool = True,
                    categories_merge: dict = None,
                    skipped_accounts: list = None) -> dict:
    """
    Import settings from CSV:
    - Creates category groups + categories
    - Creates accounts with opening balance expenses
    - Optionally stores monthly history in monthly_history.csv

    accounts_config: [{name, sub_type, currency, is_asset, opening_balance, ...}]
    categories_config: [{name, type}]
    categories_merge: {source_name: target_name} — merged categories are not
        created; their history amounts are attributed to the target instead.
    skipped_accounts: account names to exclude entirely (e.g. investment accounts).
    """
    if categories_merge is None:
        categories_merge = {}
    _skipped_accounts: set = set(skipped_accounts) if skipped_accounts else set()
    # ── 1. Category groups ───────────────────────────────────────────────────
    grp_rows = read_csv("category_groups.csv")
    existing_grp_names = {r["name"] for r in grp_rows}
    groups_created = 0
    for grp_name, grp_type in [("匯入（支出）", "expense"), ("匯入（收入）", "income")]:
        if grp_name not in existing_grp_names:
            grp_rows.append({
                "id": next_id(grp_rows),
                "name": grp_name,
                "sort_order": 90 + groups_created,
                "type": grp_type,
            })
            groups_created += 1
    if groups_created:
        write_csv("category_groups.csv", grp_rows, SCHEMA["category_groups.csv"])

    # ── 2. Categories ────────────────────────────────────────────────────────
    cat_rows = read_csv("categories.csv")
    existing_cat_names = {r["name"] for r in cat_rows}
    cats_created = 0
    for cfg in categories_config:
        name = cfg.get("name", "").strip()
        cat_type = cfg.get("type", "expense")
        if not name or name in existing_cat_names:
            continue
        if name in categories_merge:  # merged into another category — don't create
            continue
        group_name = "匯入（收入）" if cat_type == "income" else "匯入（支出）"
        cat_rows.append({
            "id": next_id(cat_rows),
            "name": name,
            "type": cat_type,
            "is_asset": 1,
            "in_budget": 1,
            "group_name": group_name,
            "sort_order": 90 + cats_created,
            "monthly_budget": 0,
        })
        existing_cat_names.add(name)
        cats_created += 1
    if cats_created:
        write_csv("categories.csv", cat_rows, SCHEMA["categories.csv"])

    # ── 4. Accounts + opening balances ───────────────────────────────────────
    acc_rows = read_csv("accounts.csv")
    existing_acc_names = {r["name"] for r in acc_rows}
    accs_created = 0

    for cfg in accounts_config:
        name = cfg.get("name", "").strip()
        if not name or name in existing_acc_names:
            continue

        sub_type  = cfg.get("sub_type", "其他")
        is_liab   = sub_type in LIABILITY_SUBTYPES
        acc_type  = "liability" if is_liab else "asset"
        currency  = cfg.get("currency", "TWD")
        is_asset  = int(cfg.get("is_asset", 1))
        icon      = ICON_MAP.get(sub_type, "👝")
        balance   = float(cfg.get("opening_balance") or 0)
        # Store signed: positive = asset funds, negative = liability debt
        opening_balance = -balance if is_liab else balance

        new_acc_id = next_id(acc_rows)
        acc_rows.append({
            "id": new_acc_id,
            "name": name,
            "icon": icon,
            "sort_order": 80 + accs_created,
            "type": acc_type,
            "sub_type": sub_type,
            "is_asset": is_asset,
            "billing_start_day": int(cfg.get("billing_start_day") or 1),
            "currency": currency,
            "credit_limit": float(cfg.get("credit_limit") or 0),
            "payment_due_day": int(cfg.get("payment_due_day") or 0),
            "min_payment_pct": float(cfg.get("min_payment_pct") or 10),
            "min_payment_floor": float(cfg.get("min_payment_floor") or 1000),
            "apr": float(cfg.get("apr") or 0),
            "opening_balance": opening_balance,
        })
        existing_acc_names.add(name)
        accs_created += 1

    if accs_created:
        write_csv("accounts.csv", acc_rows, SCHEMA["accounts.csv"])

    # ── 5. Monthly history ───────────────────────────────────────────────────
    history_months = 0
    if import_history and file_path and os.path.exists(file_path):
        # Re-aggregate from CSV
        delimiter = _detect_delimiter(file_path)
        monthly_agg = {}
        with open(file_path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.reader(f, delimiter=delimiter)
            header = next(reader, None)
            if header:
                header = [c.strip() for c in header]
                for raw_row in reader:
                    if not any(cell.strip() for cell in raw_row):
                        continue
                    row = {header[j]: raw_row[j].strip() if j < len(raw_row) else "" for j in range(len(header))}
                    raw_date   = row.get(mapping.get("date",     ""), "").strip()
                    raw_amount = row.get(mapping.get("amount",   ""), "0").strip()
                    raw_type   = row.get(mapping.get("type",     ""), "").strip()
                    raw_cat    = row.get(mapping.get("category", ""), "").strip()
                    raw_acc    = row.get(mapping.get("account",  ""), "").strip()

                    if _skipped_accounts and raw_acc in _skipped_accounts:
                        continue
                    amount = _parse_amount(raw_amount)
                    if amount == 0:
                        continue
                    mapped_type = _resolve_type(raw_type, type_mapping, raw_cat, raw_amount)
                    if mapped_type not in ("income", "expense"):
                        continue
                    if not raw_date:
                        continue
                    date = _parse_date(raw_date)
                    if len(date) < 7:
                        continue
                    try:
                        year = int(date[:4])
                        month = int(date[5:7])
                        cat_key_raw = raw_cat or "未分類"
                        cat_key = categories_merge.get(cat_key_raw, cat_key_raw)
                        key = (year, month, cat_key, mapped_type)
                        monthly_agg[key] = monthly_agg.get(key, 0) + amount
                    except ValueError:
                        pass

        if monthly_agg:
            hist_rows = read_csv("monthly_history.csv")
            for (year, month, category, t), amount in monthly_agg.items():
                hist_rows.append({
                    "id": next_id(hist_rows),
                    "year": year,
                    "month": month,
                    "category": category,
                    "type": t,
                    "amount": round(amount, 2),
                })
            write_csv("monthly_history.csv", hist_rows, SCHEMA["monthly_history.csv"])
            history_months = len({(k[0], k[1]) for k in monthly_agg})

    return {
        "accounts_created": accs_created,
        "categories_created": cats_created,
        "history_months": history_months,
    }
