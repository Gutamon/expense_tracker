import io
import os
import tempfile
import zipfile
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, abort, send_file
from app.models.account import AccountModel
from app.models.category import CategoryModel, CategoryGroupModel
from app.models import csv_store
from app.models.importer import preview_file, import_csv, extract_from_zip, analyze_import

settings_bp = Blueprint("settings", __name__)
category_model = CategoryModel()
category_group_model = CategoryGroupModel()
account_model = AccountModel()


@settings_bp.route("/settings")
def manage_settings():
    categories = category_model.get_all()
    groups = category_group_model.get_all()
    accounts = account_model.get_all()
    monthly_budget = float(csv_store.get_setting("monthly_budget", 0) or 0)
    return render_template("settings.html", categories=categories, groups=groups,
                           accounts=accounts, username="", monthly_budget=monthly_budget)


# ── Category API ─────────────────────────────────────────────────────────────

@settings_bp.route("/api/categories", methods=["POST"])
def api_create_category():
    data = request.get_json(force=True)
    name = data.get("name")
    if not name: abort(400, "缺少類別名稱")
    new_id = category_model.create(
        name=name,
        type=data.get("type", "expense"),
        is_asset=int(data.get("is_asset", 1)),
        in_budget=int(data.get("in_budget", 1)),
        group_name=data.get("group_name", "未分類"),
    )
    return jsonify({"success": True, "id": new_id}), 201


@settings_bp.route("/api/categories/<int:cat_id>", methods=["PUT"])
def api_update_category(cat_id):
    data = request.get_json(force=True)
    if category_model.update(
        cat_id=cat_id,
        name=data.get("name"),
        type=data.get("type", "expense"),
        is_asset=int(data.get("is_asset", 1)),
        in_budget=int(data.get("in_budget", 1)),
        group_name=data.get("group_name", "未分類"),
    ):
        return jsonify({"success": True})
    abort(404, "更新失敗")


@settings_bp.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def api_delete_category(cat_id):
    replace_with = request.args.get("replace_with")
    if category_model.delete(cat_id, replace_with):
        return jsonify({"success": True})
    abort(404, "刪除失敗")


@settings_bp.route("/api/categories/<int:cat_id>/budget", methods=["PUT"])
def api_update_category_budget(cat_id):
    data = request.get_json(force=True)
    if category_model.update_budget(cat_id, data.get("monthly_budget", 0)):
        return jsonify({"success": True})
    abort(404, "更新失敗")


@settings_bp.route("/api/categories/sort", methods=["POST"])
def api_sort_categories():
    data = request.get_json(force=True)
    if category_model.update_sort_orders(data.get("order", [])):
        return jsonify({"success": True})
    abort(400, "排序失敗")


# ── Groups API ────────────────────────────────────────────────────────────────

@settings_bp.route("/api/groups", methods=["POST"])
def api_create_group():
    data = request.get_json(force=True)
    name = data.get("name")
    if not name: abort(400, "缺少群組名稱")
    new_id = category_group_model.create(name, data.get("type", "expense"))
    return jsonify({"success": True, "id": new_id}), 201


@settings_bp.route("/api/groups/<int:group_id>", methods=["PUT"])
def api_update_group(group_id):
    data = request.get_json(force=True)
    if category_group_model.update(group_id, data.get("name"), data.get("type")):
        return jsonify({"success": True})
    abort(404, "更新失敗")


@settings_bp.route("/api/groups/<int:group_id>", methods=["DELETE"])
def api_delete_group(group_id):
    if category_group_model.delete(group_id):
        return jsonify({"success": True})
    abort(404, "刪除失敗")


@settings_bp.route("/api/groups/sort", methods=["POST"])
def api_sort_groups():
    data = request.get_json(force=True)
    if category_group_model.update_sort_orders(data.get("order", [])):
        return jsonify({"success": True})
    abort(400, "排序失敗")


# ── Account API ───────────────────────────────────────────────────────────────

@settings_bp.route("/api/accounts", methods=["GET"])
def api_accounts_list():
    return jsonify(account_model.get_all())


@settings_bp.route("/api/accounts", methods=["POST"])
def api_accounts_create():
    data = request.get_json(force=True)
    if "name" not in data or not data["name"].strip():
        abort(400, description="缺少帳戶名稱")
    new_id = account_model.create(
        name=data["name"].strip(),
        icon=data.get("icon", "💰"),
        type=data.get("type", "asset"),
        is_asset=int(data.get("is_asset", 1)),
        billing_start_day=int(data.get("billing_start_day", 1)),
        currency=data.get("currency", "TWD"),
        credit_limit=float(data.get("credit_limit", 0)),
    )
    return jsonify({"success": True, "id": new_id}), 201


@settings_bp.route("/api/accounts/<account_id>", methods=["PUT"])
def api_accounts_update(account_id):
    data = request.get_json(force=True)
    if not account_model.update(account_id, data):
        abort(404, description="更新失敗")
    return jsonify({"success": True})


@settings_bp.route("/api/accounts/<account_id>", methods=["DELETE"])
def api_accounts_delete(account_id):
    replace_with = request.args.get("replace_with")
    if not account_model.delete(account_id, replace_with):
        abort(404, description="刪除失敗")
    return jsonify({"success": True})


@settings_bp.route("/api/accounts/sort", methods=["POST"])
def api_sort_accounts():
    data = request.get_json(force=True)
    account_model.update_sort_orders(data.get("order", []))
    return jsonify({"success": True})


# ── Export / Import ───────────────────────────────────────────────────────────

@settings_bp.route("/api/export/zip")
def api_export_zip():
    data_dir = csv_store._data_dir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in csv_store.SCHEMA:
            filepath = os.path.join(data_dir, filename)
            if os.path.exists(filepath):
                zf.write(filepath, filename)
    buf.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d")
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=f"帳本備份_{timestamp}.zip")


@settings_bp.route("/api/import/preview", methods=["POST"])
def api_import_preview():
    f = request.files.get("file")
    if not f:
        abort(400, description="請上傳檔案")
    lower_name = f.filename.lower()
    if not any(lower_name.endswith(ext) for ext in (".csv", ".txt", ".zip")):
        abort(400, description="僅支援 CSV、TXT 或 ZIP 格式")

    suffix = ".zip" if lower_name.endswith(".zip") else (".txt" if lower_name.endswith(".txt") else ".csv")
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    extracted_path = None
    try:
        os.close(tmp_fd)
        f.save(tmp_path)

        if suffix == ".zip":
            with zipfile.ZipFile(tmp_path, "r") as zf:
                names = zf.namelist()
            # Our own backup: contains at least expenses.csv + accounts.csv
            if "expenses.csv" in names and "accounts.csv" in names:
                os.unlink(tmp_path)
                return jsonify({"type": "backup"})
            # Third-party ZIP: extract inner CSV/TXT
            extracted_path = extract_from_zip(tmp_path)
            parse_path = extracted_path
        else:
            parse_path = tmp_path

        result = preview_file(parse_path)
        result["type"] = "mapping"
        result["tmp_filename"] = os.path.basename(parse_path)
    except Exception as e:
        if extracted_path and os.path.exists(extracted_path):
            os.unlink(extracted_path)
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        abort(500, description=str(e))
    finally:
        if suffix == ".zip" and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return jsonify(result)


@settings_bp.route("/api/import/analyze", methods=["POST"])
def api_import_analyze():
    data = request.get_json(force=True)
    tmp_filename = data.get("tmp_filename")
    mapping = data.get("mapping", {})
    type_mapping = data.get("type_mapping", {})
    if not tmp_filename:
        abort(400, description="缺少 tmp_filename")
    tmp_path = os.path.join(tempfile.gettempdir(), tmp_filename)
    if not os.path.exists(tmp_path):
        abort(400, description="暫存檔案不存在，請重新上傳")
    try:
        result = analyze_import(tmp_path, mapping, type_mapping)
    except Exception as e:
        abort(500, description=str(e))
    return jsonify(result)


@settings_bp.route("/api/import/csv", methods=["POST"])
def api_import_csv():
    data = request.get_json(force=True)
    tmp_filename = data.get("tmp_filename")
    mapping = data.get("mapping", {})
    type_mapping = data.get("type_mapping", {})
    account_currencies = data.get("account_currencies", {})
    account_types = data.get("account_types", {})
    category_type_overrides = data.get("category_type_overrides", {})
    if not tmp_filename:
        abort(400, description="缺少 tmp_filename")
    tmp_path = os.path.join(tempfile.gettempdir(), tmp_filename)
    if not os.path.exists(tmp_path):
        abort(400, description="暫存檔案不存在，請重新上傳")
    try:
        result = import_csv(tmp_path, mapping, type_mapping, account_currencies, account_types, category_type_overrides)
        os.unlink(tmp_path)
    except Exception as e:
        abort(500, description=str(e))
    return jsonify({"success": True, **result})


@settings_bp.route("/api/data/wipe", methods=["POST"])
def api_data_wipe():
    for filename, fieldnames in csv_store.SCHEMA.items():
        csv_store.write_csv(filename, [], fieldnames)
    return jsonify({"success": True})


@settings_bp.route("/api/import/restore", methods=["POST"])
def api_import_restore():
    f = request.files.get("file")
    if not f or not f.filename.endswith(".zip"):
        abort(400, description="請上傳 ZIP 格式的備份檔案")

    data_dir = csv_store._data_dir()
    tmp_files = []
    try:
        with zipfile.ZipFile(f, "r") as zf:
            names = zf.namelist()
            if "expenses.csv" not in names:
                abort(400, description="備份檔案格式不正確（缺少 expenses.csv）")
            for filename in csv_store.SCHEMA:
                if filename in names:
                    tmp_path = os.path.join(data_dir, filename + ".tmp")
                    with zf.open(filename) as src, open(tmp_path, "wb") as dst:
                        dst.write(src.read())
                    tmp_files.append((tmp_path, os.path.join(data_dir, filename)))
        for tmp_path, final_path in tmp_files:
            os.replace(tmp_path, final_path)
    except Exception as e:
        for tmp_path, _ in tmp_files:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        abort(500, description=f"還原失敗：{str(e)}")

    return jsonify({"success": True})
