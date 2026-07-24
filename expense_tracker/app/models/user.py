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
# role: "owner" (this device owns its ledger) or "member" (joined someone else's via
# a 識別碼). Missing/blank on rows written before this column existed — always read it
# as (row.get("role") or "owner") so legacy single-device rows behave as owners.
REGISTRY_FIELDS = ["device_id", "display_name", "sync_id", "role", "created_at"]

SYNC_FILE = "sync_codes.csv"
SYNC_FIELDS = ["code", "sync_id", "created_at"]
# Excludes ambiguous chars (0/O, 1/I/L) since the user retypes this by hand.
_SYNC_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

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


def user_data_dir(root: str, folder_id: str) -> str:
    """Join the users/ root with a folder name (a device_id, or a sync_id shared by
    multiple devices — see effective_data_id)."""
    return os.path.join(_users_root(root), folder_id)


def resolve_data_dir(root: str, device_id: str) -> str:
    """The actual data folder for a request from this device — its own folder, or
    the shared sync-group folder if it has joined one via a 識別碼."""
    return user_data_dir(root, effective_data_id(root, device_id))


def _registry_path(root: str) -> str:
    return os.path.join(_users_root(root), REGISTRY_FILE)


def has_users(root: str) -> bool:
    """True if at least one device has been registered."""
    p = _registry_path(root)
    if not os.path.exists(p):
        return False
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return any(True for _ in csv.DictReader(f))


def register(root: str, device_id: str, display_name: str = "", role: str = "owner"):
    """Append a device to users/registry.csv. A device starts as owner of its own
    (private) folder; joining a sync group flips it to member (see join_sync_group)."""
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
            "sync_id": "",
            "role": role,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })


def _load_registry_rows(root: str) -> list:
    p = _registry_path(root)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _save_registry_rows(root: str, rows: list):
    os.makedirs(_users_root(root), exist_ok=True)
    with open(_registry_path(root), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _registry_row(root: str, device_id: str) -> dict | None:
    for row in _load_registry_rows(root):
        if row.get("device_id") == device_id:
            return row
    return None


def effective_data_id(root: str, device_id: str) -> str:
    """Return the folder name this device's data actually lives under.

    A device that has joined a 識別碼 sync group shares its folder (named by the
    group's sync_id) with every other device in that group. An unsynced device is
    simply keyed by its own device_id, exactly as before this feature existed.
    """
    row = _registry_row(root, device_id)
    sync_id = (row or {}).get("sync_id") or ""
    return sync_id or device_id


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


# ── Sync codes (識別碼) ────────────────────────────────────────────────────────
# A 識別碼 identifies a shared ledger, not a single device. It serves two purposes:
#   1. Cookie loss: typing it into onboarding re-attaches this browser to the ledger
#      without needing the ZIP backup (replaces the old rescue-code cookie-swap).
#   2. Multi-device sync: entering the same code on another device's onboarding
#      screen makes both devices read/write the same folder — no primary/secondary,
#      both have equal read/write access.
#
# Internally, a sync group's shared folder is named after a sync_id (a fresh UUID,
# distinct from any device_id). registry.csv's sync_id column records which group
# each device belongs to; effective_data_id() resolves it. A device with no sync_id
# is simply keyed by its own device_id, unchanged from pre-sync behavior.

def _sync_codes_path(root: str) -> str:
    return os.path.join(_users_root(root), SYNC_FILE)


def _load_sync_rows(root: str) -> list:
    p = _sync_codes_path(root)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _save_sync_rows(root: str, rows: list):
    os.makedirs(_users_root(root), exist_ok=True)
    with open(_sync_codes_path(root), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SYNC_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _generate_code() -> str:
    raw = "".join(secrets.choice(_SYNC_ALPHABET) for _ in range(8))
    return raw[:4] + "-" + raw[4:]


def _set_device_sync_id(root: str, device_id: str, sync_id: str, role: str | None = None):
    """Update a device's sync_id (and optionally its role) in one registry save."""
    def apply(row):
        row["sync_id"] = sync_id
        if role is not None:
            row["role"] = role

    rows = _load_registry_rows(root)
    found = False
    for row in rows:
        if row.get("device_id") == device_id:
            apply(row)
            found = True
            break
    # Self-heal an orphaned device: a browser can hold a validly-signed device_id
    # cookie whose registry row no longer exists (e.g. the users/ folder was wiped
    # out-of-band). Without this, joining a 識別碼 would loop over the registry, find
    # nothing to update, and silently persist no sync_id — so 認回 would report success
    # yet never actually attach. Registering the row here makes the join take effect.
    if not found:
        register(root, device_id)
        rows = _load_registry_rows(root)
        for row in rows:
            if row.get("device_id") == device_id:
                apply(row)
                break
    _save_registry_rows(root, rows)


def get_sync_code(root: str, sync_id: str) -> str | None:
    for row in _load_sync_rows(root):
        if row.get("sync_id") == sync_id:
            return row.get("code")
    return None


def _promote_to_sync_group(root: str, device_id: str) -> str:
    """Turn an unsynced device into a sync group of one under a fresh sync_id.

    A sync_id must never equal any device_id: leaving a group only clears that
    device's own registry row, and if the group id and a member's device_id were
    the same string, that member would still (wrongly) count as a group match after
    leaving. So promotion always mints a new UUID and moves the device's existing
    folder onto it, rather than reusing the device_id as its own group id.
    """
    old_dir = user_data_dir(root, device_id)
    sync_id = new_device_id()
    new_dir = user_data_dir(root, sync_id)
    if os.path.isdir(old_dir):
        os.replace(old_dir, new_dir)
    else:
        os.makedirs(new_dir, exist_ok=True)
    _set_device_sync_id(root, device_id, sync_id)
    return sync_id


def sync_code_if_exists(root: str, device_id: str) -> str | None:
    """Return this device's 識別碼 without creating one.

    Read-only, no side effects — safe to call on every page load (e.g. the shell,
    which loads several tabs as concurrent same-origin iframes). Promoting an
    unsynced device moves its data folder on disk (see _promote_to_sync_group);
    doing that from a handler that can race with sibling requests risks one of
    them reading mid-move and seeing an empty folder. Only ensure_sync_code, called
    from the standalone 設定 page, is allowed to promote.
    """
    sync_id = effective_data_id(root, device_id)
    return get_sync_code(root, sync_id)


def ensure_sync_code(root: str, device_id: str) -> str:
    """Return this device's 識別碼, generating its sync group on first use.

    An unsynced device is promoted to a sync group of one (see
    _promote_to_sync_group) and a code is minted pointing at it. A device that
    already belongs to a group just returns that group's existing code.

    Only call this from a request that can't race with a sibling request for the
    same device (see sync_code_if_exists) — e.g. the standalone 設定 page, not the
    shell (which loads several tabs as concurrent same-origin iframes).
    """
    sync_id = effective_data_id(root, device_id)
    existing = get_sync_code(root, sync_id)
    if existing:
        return existing
    if sync_id == device_id:
        sync_id = _promote_to_sync_group(root, device_id)
    code = _generate_code()
    rows = [r for r in _load_sync_rows(root) if r.get("sync_id") != sync_id]
    rows.append({
        "code": code,
        "sync_id": sync_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_sync_rows(root, rows)
    return code


def regenerate_sync_code(root: str, device_id: str) -> str:
    """Issue a new 識別碼 for this device's sync group, invalidating the previous one."""
    sync_id = effective_data_id(root, device_id)
    if sync_id == device_id:
        sync_id = _promote_to_sync_group(root, device_id)
    rows = [r for r in _load_sync_rows(root) if r.get("sync_id") != sync_id]
    code = _generate_code()
    rows.append({
        "code": code,
        "sync_id": sync_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    _save_sync_rows(root, rows)
    return code


def resolve_sync_code(root: str, code: str) -> str | None:
    """Return the sync_id for a 識別碼, or None if unknown."""
    if not code:
        return None
    needle = code.strip().upper().replace(" ", "").replace("-", "")
    for row in _load_sync_rows(root):
        haystack = (row.get("code") or "").upper().replace("-", "")
        if haystack == needle:
            return row.get("sync_id")
    return None


def join_sync_group(root: str, device_id: str, sync_id: str):
    """Attach this (fresh, first-run) device to an existing sync group as a member —
    this is where a 從裝置 (slave) is born. The group's owner is the device that
    originally minted the sync group (see _promote_to_sync_group), never touched here."""
    _set_device_sync_id(root, device_id, sync_id, role="member")


def linked_device_count(root: str, device_id: str) -> int:
    """How many devices (including this one) share this device's effective data.

    An unsynced device is always a group of one. A synced device's group size is
    the count of registry rows carrying that same sync_id (never the device's own
    device_id — see _promote_to_sync_group for why the two must never collide).
    """
    row = _registry_row(root, device_id)
    sync_id = (row or {}).get("sync_id") or ""
    if not sync_id:
        return 1
    return sum(1 for r in _load_registry_rows(root) if r.get("sync_id") == sync_id)


def leave_sync_group(root: str, device_id: str):
    """Detach this device from its sync group, giving it back its own private
    folder (named by its own device_id, initially empty — onboarding runs again).
    It owns that fresh folder, so role returns to owner."""
    _set_device_sync_id(root, device_id, "", role="owner")


def is_owner(root: str, device_id: str) -> bool:
    """True if this device owns its ledger (owner of its sync group, or an unsynced
    single device). Legacy rows with no role column read as owner."""
    row = _registry_row(root, device_id)
    return ((row or {}).get("role") or "owner") == "owner"


def group_members(root: str, device_id: str) -> list:
    """Every device sharing this device's effective data folder, oldest first.

    Returns [{device_id, role, created_at, is_self}]. An unsynced device is a group
    of just itself. Read-only (no folder move) — safe alongside the shell's iframes.
    """
    sync_id = (_registry_row(root, device_id) or {}).get("sync_id") or ""
    if not sync_id:
        me = _registry_row(root, device_id) or {}
        return [{
            "device_id": device_id,
            "role": (me.get("role") or "owner"),
            "created_at": me.get("created_at") or "",
            "is_self": True,
        }]
    members = [
        {
            "device_id": r.get("device_id"),
            "role": (r.get("role") or "owner"),
            "created_at": r.get("created_at") or "",
            "is_self": r.get("device_id") == device_id,
        }
        for r in _load_registry_rows(root)
        if r.get("sync_id") == sync_id
    ]
    members.sort(key=lambda m: m["created_at"])
    return members


def kick_device(root: str, owner_device_id: str, target_device_id: str):
    """Owner removes a 從裝置 from the sync group. Returns (ok, error).

    Only detaches the target (clears its sync_id, role back to owner — it lands on its
    own empty folder and re-onboards on its next request). The group's 識別碼 is left
    intact, so other members are unaffected and the code keeps working.
    """
    if not is_owner(root, owner_device_id):
        return False, "只有主裝置可以移除其他裝置"
    owner_row = _registry_row(root, owner_device_id)
    sync_id = (owner_row or {}).get("sync_id") or ""
    if not sync_id:
        return False, "此裝置未與其他裝置同步"
    if target_device_id == owner_device_id:
        return False, "無法移除主裝置自己"
    target_row = _registry_row(root, target_device_id)
    if not target_row or (target_row.get("sync_id") or "") != sync_id:
        return False, "找不到該裝置或其不在此群組"
    _set_device_sync_id(root, target_device_id, "", role="owner")
    return True, None


def clear_sync_code(root: str, sync_id: str):
    """Drop a sync group's 識別碼 and detach every device in it. Called when the
    group's data is wiped, so devices can't be silently auto-recovered back into a
    first-run loop, and so a wiped shared folder isn't left reachable by a stale code."""
    rows = _load_sync_rows(root)
    remaining = [r for r in rows if r.get("sync_id") != sync_id]
    if len(remaining) != len(rows):
        _save_sync_rows(root, remaining)
    registry_rows = _load_registry_rows(root)
    changed = False
    for row in registry_rows:
        if row.get("sync_id") == sync_id:
            row["sync_id"] = ""
            changed = True
    if changed:
        _save_registry_rows(root, registry_rows)
