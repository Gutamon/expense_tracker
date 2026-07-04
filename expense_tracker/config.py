import os

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "app", "data")
    SECRET_KEY = "vibe_expense_secret_key"

    # Per-device isolation: each device's CSVs live under DATA_DIR/<USERS_SUBDIR>/<device_id>/
    USERS_SUBDIR = "users"
    # device_id cookie lifetime (~10 years)
    DEVICE_COOKIE_MAX_AGE = 10 * 365 * 24 * 3600
