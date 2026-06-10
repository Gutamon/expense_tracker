from flask import Blueprint, render_template, jsonify, redirect
from app.models.category import CategoryModel, CategoryGroupModel
from app.models.account import AccountModel
from app.models import csv_store

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
    return jsonify({"success": True})
