from flask import Blueprint, render_template, request, jsonify, session, abort, redirect
from app.models.account import AccountModel
from app.models.category import CategoryModel, CategoryGroupModel
from app.models.db import get_db

settings_bp = Blueprint("settings", __name__)
category_model = CategoryModel()
category_group_model = CategoryGroupModel()
account_model = AccountModel()

@settings_bp.before_request
def require_login():
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({"error": "未登入"}), 401
        return redirect('/login')

@settings_bp.route("/settings")
def manage_settings():
    user_id = session['user_id']
    categories = category_model.get_by_user(user_id)
    groups = category_group_model.get_by_user(user_id)
    accounts = account_model.get_by_user(user_id)
    with get_db() as conn:
        row = conn.execute("SELECT monthly_budget FROM users WHERE id = ?", (user_id,)).fetchone()
        monthly_budget = row['monthly_budget'] if row else 0
    return render_template("settings.html", categories=categories, groups=groups, accounts=accounts, username=session.get('username'), monthly_budget=monthly_budget)

@settings_bp.route("/api/categories", methods=["POST"])
def api_create_category():
    data = request.get_json(force=True)
    name = data.get("name")
    if not name: abort(400, "缺少類別名稱")
    new_id = category_model.create(
        user_id=session['user_id'], 
        name=name,
        type=data.get("type", "expense"),
        is_asset=int(data.get("is_asset", 1)),
        in_budget=int(data.get("in_budget", 1)),
        group_name=data.get("group_name", "未分類")
    )
    return jsonify({"success": True, "id": new_id}), 201

@settings_bp.route("/api/categories/<int:cat_id>", methods=["PUT"])
def api_update_category(cat_id):
    data = request.get_json(force=True)
    if category_model.update(
        cat_id=cat_id, 
        user_id=session['user_id'], 
        name=data.get("name"),
        type=data.get("type", "expense"),
        is_asset=int(data.get("is_asset", 1)),
        in_budget=int(data.get("in_budget", 1)),
        group_name=data.get("group_name", "未分類")
    ):
        return jsonify({"success": True})
    abort(404, "更新失敗")

@settings_bp.route("/api/categories/<int:cat_id>", methods=["DELETE"])
def api_delete_category(cat_id):
    replace_with = request.args.get("replace_with")
    if category_model.delete(cat_id, session['user_id'], replace_with):
        return jsonify({"success": True})
    abort(404, "刪除失敗")

@settings_bp.route("/api/categories/<int:cat_id>/budget", methods=["PUT"])
def api_update_category_budget(cat_id):
    data = request.get_json(force=True)
    if category_model.update_budget(cat_id, session['user_id'], data.get("monthly_budget", 0)):
        return jsonify({"success": True})
    abort(404, "更新失敗")

@settings_bp.route("/api/categories/sort", methods=["POST"])
def api_sort_categories():
    data = request.get_json(force=True)
    if category_model.update_sort_orders(session['user_id'], data.get("order", [])):
        return jsonify({"success": True})
    abort(400, "排序失敗")

# ── Groups API ──────────────────────────────────────────────────────────

@settings_bp.route("/api/groups", methods=["POST"])
def api_create_group():
    data = request.get_json(force=True)
    name = data.get("name")
    if not name: abort(400, "缺少群組名稱")
    new_id = category_group_model.create(session['user_id'], name, data.get("type", "expense"))
    return jsonify({"success": True, "id": new_id}), 201

@settings_bp.route("/api/groups/<int:group_id>", methods=["PUT"])
def api_update_group(group_id):
    data = request.get_json(force=True)
    if category_group_model.update(group_id, session['user_id'], data.get("name"), data.get("type")):
        return jsonify({"success": True})
    abort(404, "更新失敗")

@settings_bp.route("/api/groups/<int:group_id>", methods=["DELETE"])
def api_delete_group(group_id):
    if category_group_model.delete(group_id, session['user_id']):
        return jsonify({"success": True})
    abort(404, "刪除失敗")

@settings_bp.route("/api/groups/sort", methods=["POST"])
def api_sort_groups():
    data = request.get_json(force=True)
    if category_group_model.update_sort_orders(session['user_id'], data.get("order", [])):
        return jsonify({"success": True})
    abort(400, "排序失敗")

# ── Account API ──────────────────────────────────────────────────────────

@settings_bp.route("/api/accounts", methods=["GET"])
def api_accounts_list():
    return jsonify(account_model.get_by_user(session['user_id']))

@settings_bp.route("/api/accounts", methods=["POST"])
def api_accounts_create():
    data = request.get_json(force=True)
    if "name" not in data or not data["name"].strip():
        abort(400, description="缺少帳戶名稱")
    new_id = account_model.create(
        user_id=session['user_id'],
        name=data["name"].strip(),
        icon=data.get("icon", "💰"),
        type=data.get("type", "asset"),
        is_asset=int(data.get("is_asset", 1)),
        billing_start_day=int(data.get("billing_start_day", 1))
    )
    return jsonify({"success": True, "id": new_id}), 201

@settings_bp.route("/api/accounts/<account_id>", methods=["PUT"])
def api_accounts_update(account_id):
    data = request.get_json(force=True)
    if not account_model.update(account_id, session['user_id'], data):
        abort(404, description="更新失敗")
    return jsonify({"success": True})

@settings_bp.route("/api/accounts/<account_id>", methods=["DELETE"])
def api_accounts_delete(account_id):
    replace_with = request.args.get("replace_with")
    if not account_model.delete(account_id, session['user_id'], replace_with):
        abort(404, description="刪除失敗")
    return jsonify({"success": True})

@settings_bp.route("/api/accounts/sort", methods=["POST"])
def api_sort_accounts():
    data = request.get_json(force=True)
    account_model.update_sort_orders(session['user_id'], data.get("order", []))
    return jsonify({"success": True})