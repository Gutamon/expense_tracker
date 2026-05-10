import os

class Config:
    # 獲取專案根目錄的絕對路徑
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    
    # 資料庫檔案路徑
    DATABASE = os.path.join(BASE_DIR, "DataBase.db")
    
    # Session 密鑰
    SECRET_KEY = "vibe_expense_secret_key"
