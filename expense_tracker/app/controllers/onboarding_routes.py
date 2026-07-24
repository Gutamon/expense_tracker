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


def _do_join(code: str):
    """Resolve a 識別碼, attach this browser's device to its sync group, and return
    (device_id, error). Shared by the JSON validate endpoint and the GET committer.

    Covers both cookie-loss recovery (this browser has no cookie — mints a device_id
    and joins the group) and genuine multi-device sync (a second device joins the same
    group as the first, both keeping their own device_id/cookie and gaining equal
    read/write access to the shared folder).
    """
    root = csv_store.root_dir()
    sync_id = user.resolve_sync_code(root, code)
    if not sync_id:
        return None, "識別碼無效或已失效"
    device_id = user.resolve_device_id(request)
    if device_id is None:
        device_id = user.adopt_or_create(root)
    user.join_sync_group(root, device_id, sync_id)
    return device_id, None


@onboarding_bp.route("/api/onboarding/join-by-code", methods=["POST"])
def join_by_code():
    """Validate a 識別碼 (used by autoRecover / to show an error before navigating).

    NOTE: the cookie this sets on the XHR response is NOT relied upon — an iOS
    home-screen PWA routinely fails to persist a Set-Cookie from a fetch/XHR to the
    following navigation, which is exactly what made a manual 認回 report success yet
    reload straight back into onboarding as a brand-new empty device. The actual join
    that must "stick" happens on the GET /onboarding/join top-level navigation below,
    whose Set-Cookie rides a real document response and commits reliably.
    """
    code = (request.get_json(silent=True) or {}).get("code", "")
    device_id, err = _do_join(code)
    if err:
        return jsonify({"error": err}), 404
    resp = jsonify({"success": True})
    user.set_device_cookie(resp, device_id)
    return resp


@onboarding_bp.route("/onboarding/join")
def join_by_code_nav():
    """Top-level navigation join — the reliable path for iOS home-screen PWAs.

    The onboarding form points the whole page here (not a fetch) so the device cookie
    is set on a genuine document response, which iOS commits before the redirect to /
    is followed. A bad/expired code bounces back to onboarding with an error flag.
    """
    code = request.args.get("code", "")
    device_id, err = _do_join(code)
    if err:
        return redirect("/onboarding?join_error=1")
    resp = redirect("/")
    user.set_device_cookie(resp, device_id)
    return resp
