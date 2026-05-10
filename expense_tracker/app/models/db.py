import sqlite3

import os
from flask import current_app

def get_db():
    # 優先從 Flask config 取得路徑，若不在 app context 則使用相對路徑
    try:
        db_path = current_app.config['DATABASE']
    except RuntimeError:
        #  fallback 到根目錄的 DataBase.db
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "DataBase.db")
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            )
        ''')
        try: conn.execute("ALTER TABLE users ADD COLUMN monthly_budget REAL DEFAULT 0")
        except sqlite3.OperationalError: pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        try: conn.execute("ALTER TABLE categories ADD COLUMN type TEXT DEFAULT 'expense'")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE categories ADD COLUMN is_asset BOOLEAN DEFAULT 1")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE categories ADD COLUMN in_budget BOOLEAN DEFAULT 1")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE categories ADD COLUMN group_name TEXT DEFAULT ''")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE categories ADD COLUMN monthly_budget REAL DEFAULT 0")
        except sqlite3.OperationalError: pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS category_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        try: conn.execute("ALTER TABLE category_groups ADD COLUMN type TEXT DEFAULT 'expense'")
        except sqlite3.OperationalError: pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_monthly_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                amount REAL DEFAULT 0,
                UNIQUE(user_id, year, month),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS cat_monthly_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL,
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                amount REAL DEFAULT 0,
                UNIQUE(user_id, category_id, year, month),
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        try: conn.execute("ALTER TABLE expenses ADD COLUMN type TEXT DEFAULT 'expense'")
        except sqlite3.OperationalError: pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS stocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                shares REAL DEFAULT 0,
                avg_price REAL DEFAULT 0,
                current_price REAL DEFAULT 0,
                updated_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')

        try: conn.execute("ALTER TABLE stocks ADD COLUMN account_id INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass

        conn.execute('''
            CREATE TABLE IF NOT EXISTS stock_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                stock_id INTEGER NOT NULL,
                type TEXT NOT NULL,  -- buy, sell, dividend, split
                date TEXT NOT NULL,
                shares REAL DEFAULT 0,
                price REAL DEFAULT 0,
                fee REAL DEFAULT 0,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(stock_id) REFERENCES stocks(id)
            )
        ''')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                icon TEXT DEFAULT '💰',
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        ''')
        try: conn.execute("ALTER TABLE accounts ADD COLUMN type TEXT DEFAULT 'asset'")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE accounts ADD COLUMN is_asset BOOLEAN DEFAULT 1")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE expenses ADD COLUMN account_id INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass
        try: conn.execute("ALTER TABLE expenses ADD COLUMN to_account_id INTEGER DEFAULT 0")
        except sqlite3.OperationalError: pass