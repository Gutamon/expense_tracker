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


@onboarding_bp.route("/api/onboarding/restore-device", methods=["POST"])
def restore_device():
    """Re-attach this browser to a device's data folder via its rescue code."""
    code = (request.get_json(silent=True) or {}).get("code", "")
    device_id = user.resolve_rescue_code(csv_store.root_dir(), code)
    if not device_id:
        return jsonify({"error": "救援碼無效或已失效"}), 404
    resp = jsonify({"success": True})
    user.set_device_cookie(resp, device_id)
    return resp
