from flask import Blueprint, render_template, request, jsonify, redirect
from app.models.category import CategoryModel, CategoryGroupModel
from app.models.account import AccountModel
from app.models import csv_store, user

onboarding_bp = Blueprint("onboarding", __name__)
category_model = CategoryModel()
account_model = AccountModel()
category_group_model = CategoryGroupModel()


@onboarding_bp.route("/onboarding")
def onboarding():
    if not csv_store.is_first_run():
        return redirect("/")
    return render_template("onboarding.html")


@onboarding_bp.route("/api/onboarding/fresh", methods=["POST"])
def api_onboarding_fresh():
    category_model.create_defaults()
    account_model.ensure_defaults()
    csv_store.set_setting("onboarded", "true")
    return jsonify({"success": True})


@onboarding_bp.route("/api/onboarding/join-by-code", methods=["POST"])
def join_by_code():
    """Attach this browser's device to a 識別碼's sync group.

    Covers both cookie-loss recovery (this browser has no cookie — reuses/mints a
    device_id and joins the group) and genuine multi-device sync (a second device
    joins the same group as the first, both keeping their own device_id/cookie and
    gaining equal read/write access to the shared folder).
    """
    code = (request.get_json(silent=True) or {}).get("code", "")
    root = csv_store.root_dir()
    sync_id = user.resolve_sync_code(root, code)
    if not sync_id:
        return jsonify({"error": "識別碼無效或已失效"}), 404

    device_id = user.resolve_device_id(request)
    resp = jsonify({"success": True})
    if device_id is None:
        device_id = user.adopt_or_create(root)
        user.set_device_cookie(resp, device_id)
    user.join_sync_group(root, device_id, sync_id)
    return resp
