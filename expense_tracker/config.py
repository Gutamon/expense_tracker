import os

class Config:
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "app", "data")
    SECRET_KEY = "vibe_expense_secret_key"
