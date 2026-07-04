"""Device identity + user registry — the seam for multi-user isolation.

Each device that opens the app is a self-contained user. Identity is a signed
`device_id` cookie; that device's CSV files live under
`<root>/<USERS_SUBDIR>/<device_id>/`. This module is the single place that resolves
"who is this request", so future login / account / cloud-sync logic can replace the
cookie mechanism here without touching any model or controller.
"""

import csv
import os
import uuid
from datetime import datetime

from itsdangerous import BadData, URLSafeSerializer

from config import Config

COOKIE_NAME = "device_id"
REGISTRY_FILE = "registry.csv"
REGISTRY_FIELDS = ["device_id", "display_name", "created_at"]

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


def _list_devices(root: str) -> list:
    """Return all rows from registry.csv."""
    p = _registry_path(root)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # Strip stray BOM characters from device_id values caused by the old
    # utf-8-sig append bug (BOM inserted mid-file before each appended row).
    for row in rows:
        if "device_id" in row:
            row["device_id"] = row["device_id"].lstrip("﻿")
    return rows


def _is_device_onboarded(device_dir: str) -> bool:
    """Return True if this device folder has a completed onboarding marker."""
    settings_path = os.path.join(device_dir, "settings.csv")
    if not os.path.exists(settings_path):
        return False
    with open(settings_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("key") == "onboarded" and row.get("value") == "true":
                return True
    return False


def adopt_or_create(root: str) -> str:
    """Resolve a device with no valid cookie into a device id.

    Single-user auto-recovery: if exactly one device is registered and has
    completed onboarding, re-adopt it instead of creating a new empty device.
    This preserves data when the cookie is lost (browser clear, incognito, etc.).

    Otherwise: first device adopts legacy top-level CSVs; every later device
    starts fresh with an empty folder and onboarding.
    """
    registered = _list_devices(root)

    # Re-adopt the most recently registered device that has completed onboarding.
    # Using "most recent" instead of "exactly one" handles the case where multiple
    # test sessions each left a separate onboarded device in the registry.
    onboarded = [(r["device_id"], r.get("created_at", ""))
                 for r in registered
                 if _is_device_onboarded(user_data_dir(root, r["device_id"]))]
    if onboarded:
        latest_id = max(onboarded, key=lambda x: x[1])[0]
        return latest_id  # caller will re-set the cookie via after_request

    device_id = new_device_id()
    target = user_data_dir(root, device_id)

    legacy = [] if has_users(root) else _legacy_csvs_at_root(root)
    if legacy:
        os.makedirs(target, exist_ok=True)
        for filename in legacy:
            os.replace(os.path.join(root, filename), os.path.join(target, filename))

    register(root, device_id)
    return device_id
