"""Device identity + user registry — the seam for multi-user isolation.

Each device that opens the app is a self-contained user. Identity is a signed
`device_id` cookie; that device's CSV files live under
`<root>/<USERS_SUBDIR>/<device_id>/`. This module is the single place that resolves
"who is this request", so future login / account / cloud-sync logic can replace the
cookie mechanism here without touching any model or controller.
"""

import csv
import os
import secrets
import uuid
from datetime import datetime

from itsdangerous import BadData, URLSafeSerializer

from config import Config

COOKIE_NAME = "device_id"
REGISTRY_FILE = "registry.csv"
REGISTRY_FIELDS = ["device_id", "display_name", "created_at"]

RESCUE_FILE = "rescue_codes.csv"
RESCUE_FIELDS = ["code", "device_id", "created_at"]
# Excludes ambiguous chars (0/O, 1/I/L) since the user retypes this by hand.
_RESCUE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

# App-data CSVs (from csv_store.SCHEMA) plus any stray top-level CSVs are moved into
# the first device's folder on adoption. registry.csv itself lives in users/, so it
# is never at the root and never conflicts.

_SALT = "device-id"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(Config.SECRET_KEY, salt=_SALT)


def new_device_id() -> str:
    return uuid.uuid4().hex


def sign(device_id: str) -> str:
    """Return the signed cookie value for a device id."""
    return _serializer().dumps(device_id)


def set_device_cookie(response, device_id: str):
    """Attach the signed device_id cookie to a response.

    Marked Secure when the request reached us over HTTPS — checked via
    X-Forwarded-Proto so it works behind the ngrok/Cloudflare TLS proxy (where Flask's
    own scheme is http) while still setting a usable cookie for plain-http local dev.
    A Secure cookie over HTTPS also persists more reliably in an iOS home-screen PWA.
    """
    from flask import request
    is_https = request.headers.get("X-Forwarded-Proto", request.scheme) == "https"
    response.set_cookie(
        COOKIE_NAME,
        sign(device_id),
        max_age=Config.DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=is_https,
        path="/",
    )


def resolve_device_id(request) -> str | None:
    """Return the verified device id from the request cookie, or None."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        return _serializer().loads(raw)
    except BadData:
        return None


def _users_root(root: str) -> str:
    return os.path.join(root, Config.USERS_SUBDIR)


def user_data_dir(root: str, device_id: str) -> str:
    return os.path.join(_users_root(root), device_id)


def _registry_path(root: str) -> str:
    return os.path.join(_users_root(root), REGISTRY_FILE)


def has_users(root: str) -> bool:
    """True if at least one device has been registered."""
    p = _registry_path(root)
    if not os.path.exists(p):
        return False
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return any(True for _ in csv.DictReader(f))


def register(root: str, device_id: str, display_name: str = ""):
    """Append a device to users/registry.csv."""
    os.makedirs(_users_root(root), exist_ok=True)
    p = _registry_path(root)
    exists = os.path.exists(p)
    # utf-8-sig only for new files (writes BOM once at start).
    # Appending with utf-8-sig inserts a BOM mid-file, corrupting subsequent rows.
    enc = "utf-8-sig" if not exists else "utf-8"
    with open(p, "a", encoding=enc, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "device_id": device_id,
            "display_name": display_name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def _legacy_csvs_at_root(root: str) -> list:
    """Top-level *.csv files that predate per-device isolation."""
    if not os.path.isdir(root):
        return []
    return [f for f in os.listdir(root)
            if f.endswith(".csv") and os.path.isfile(os.path.join(root, f))]


def adopt_or_create(root: str) -> str:
    """Resolve a device with no valid cookie into a brand new, empty device id.

    Every cookie-less request gets its own fresh folder. We deliberately do NOT
    re-adopt an existing device's data on a missing cookie: on a fixed public URL
    (ngrok) that would hand one person's ledger to the next stranger who opens it.
    Losing the cookie (browser clear / incognito / a different device) therefore
    means starting fresh — the accepted trade-off for having no login. Use the ZIP
    export as a manual safeguard against loss.
    """
    device_id = new_device_id()
    target = user_data_dir(root, device_id)

    # One-time migration from the pre-per-device layout: the very first device to
    # connect adopts any stray top-level CSVs into its own folder.
    legacy = [] if has_users(root) else _legacy_csvs_at_root(root)
    if legacy:
        os.makedirs(target, exist_ok=True)
        for filename in legacy:
            os.replace(os.path.join(root, filename), os.path.join(target, filename))

    register(root, device_id)
    return device_id


# ── Rescue codes ─────────────────────────────────────────────────────────────
# A device can generate a short, human-typeable code (shown in 設定) that maps back
# to its folder. Losing the device_id cookie normally means starting fresh (see
# adopt_or_create); typing this code into the onboarding screen re-attaches the
# cookie to the original device without needing the ZIP backup.

def _rescue_path(root: str) -> str:
    return os.path.join(_users_root(root), RESCUE_FILE)


def _load_rescue_rows(root: str) -> list:
    p = _rescue_path(root)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _save_rescue_rows(root: str, rows: list):
    os.makedirs(_users_root(root), exist_ok=True)
    with open(_rescue_path(root), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESCUE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _generate_code() -> str:
    raw = "".join(secrets.choice(_RESCUE_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def get_rescue_code(root: str, device_id: str) -> str | None:
    for row in _load_rescue_rows(root):
        if row.get("device_id") == device_id:
            return row.get("code")
    return None


def ensure_rescue_code(root: str, device_id: str) -> str:
    """Return this device's rescue code, generating one on first use."""
    existing = get_rescue_code(root, device_id)
    if existing:
        return existing
    return regenerate_rescue_code(root, device_id)


def regenerate_rescue_code(root: str, device_id: str) -> str:
    """Issue a new rescue code for this device, invalidating any previous one."""
    rows = [r for r in _load_rescue_rows(root) if r.get("device_id") != device_id]
    code = _generate_code()
    rows.append({
        "code": code,
        "device_id": device_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_rescue_rows(root, rows)
    return code


def clear_rescue_code(root: str, device_id: str):
    """Drop a device's rescue code. Called when its data is wiped, so a now-empty
    device can't be silently auto-recovered back into a first-run loop."""
    rows = _load_rescue_rows(root)
    remaining = [r for r in rows if r.get("device_id") != device_id]
    if len(remaining) != len(rows):
        _save_rescue_rows(root, remaining)


def resolve_rescue_code(root: str, code: str) -> str | None:
    """Return the device_id for a rescue code, or None if unknown."""
    if not code:
        return None
    needle = code.strip().upper().replace(" ", "").replace("-", "")
    for row in _load_rescue_rows(root):
        haystack = (row.get("code") or "").upper().replace("-", "")
        if haystack == needle:
            return row.get("device_id")
    return None
