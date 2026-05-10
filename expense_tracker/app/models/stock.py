import re
import math
from datetime import datetime
from app.models.db import get_db
import yfinance as yf

class StockModel:
    def get_by_user(self, user_id: int):
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM stocks WHERE user_id = ?", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_transactions(self, user_id: int, stock_id: int = None):
        with get_db() as conn:
            if stock_id:
                rows = conn.execute("SELECT * FROM stock_transactions WHERE user_id = ? AND stock_id = ? ORDER BY date DESC, id DESC", (user_id, stock_id)).fetchall()
            else:
                rows = conn.execute("SELECT t.*, s.symbol, s.name FROM stock_transactions t JOIN stocks s ON t.stock_id = s.id WHERE t.user_id = ? ORDER BY t.date DESC, t.id DESC", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def create_position(self, user_id: int, symbol: str, name: str, account_id: int):
        with get_db() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT * FROM stocks WHERE user_id = ? AND symbol = ?", (user_id, symbol)).fetchone()
            if row:
                return False # 已經存在
            cursor.execute("INSERT INTO stocks (user_id, symbol, name, account_id) VALUES (?, ?, ?, ?)", (user_id, symbol, name, account_id))
            return cursor.lastrowid

    def _update_stock_avg(self, conn, stock_id: int):
        rows = conn.execute("SELECT * FROM stock_transactions WHERE stock_id = ? ORDER BY date ASC, id ASC", (stock_id,)).fetchall()
        shares = 0.0
        total_cost = 0.0
        for r in rows:
            t_type = r['type']
            t_shares = r['shares']
            t_price = r['price']
            if t_type == 'buy':
                shares += t_shares
                total_cost += t_shares * t_price
            elif t_type == 'sell':
                if shares > 0:
                    avg_cost = total_cost / shares
                    total_cost -= t_shares * avg_cost
                shares -= t_shares
                if shares <= 0:
                    shares = 0
                    total_cost = 0
            elif t_type == 'split':
                # split ratio is stored in 'price' (e.g. 2 means 1 share becomes 2)
                # cost basis remains the same, shares multiply
                shares = shares * t_price

        # 確保股數是整數
        shares = int(round(shares))
        avg_price = (total_cost / shares) if shares > 0 else 0
        conn.execute("UPDATE stocks SET shares = ?, avg_price = ? WHERE id = ?", (shares, avg_price, stock_id))

    def add_transaction(self, user_id: int, stock_id: int, t_type: str, date: str, shares: float, price: float, fee: float, note: str):
        shares = int(shares) # 確保輸入時也是整數
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db() as conn:
            cursor = conn.cursor()
            
            # 取得該股票的交割帳號與名稱
            stock_info = cursor.execute("SELECT account_id, symbol FROM stocks WHERE id = ?", (stock_id,)).fetchone()
            settlement_acc_id = stock_info["account_id"]
            symbol = stock_info["symbol"]
            
            # 取得或建立「股票交易」帳戶
            stock_acc = cursor.execute("SELECT id FROM accounts WHERE user_id = ? AND name = '股票交易'", (user_id,)).fetchone()
            if stock_acc:
                inventory_acc_id = stock_acc["id"]
            else:
                cursor.execute("INSERT INTO accounts (user_id, name, icon, type, sort_order, is_asset) VALUES (?, '股票交易', '📈', 'asset', 99, 1)", (user_id,))
                inventory_acc_id = cursor.lastrowid
                
            cursor.execute('''
                INSERT INTO stock_transactions (user_id, stock_id, type, date, shares, price, fee, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, stock_id, t_type, date, shares, price, fee, note, created_at))
            
            # 建立關聯的轉帳紀錄 (買入：交割 -> 庫存；賣出/股利：庫存 -> 交割)
            # 買入的總花費 (扣除交割帳戶)
            # 賣出的總得款 (存入交割帳戶)
            # 股利的總得款 (存入交割帳戶)
            # 買入時轉帳：從 settlement_acc_id 到 inventory_acc_id
            # 賣出時轉帳：從 inventory_acc_id 到 settlement_acc_id
            
            amount = 0
            from_acc = None
            to_acc = None
            title = ""
            
            if t_type == "buy":
                amount = shares * price + fee
                from_acc = settlement_acc_id
                to_acc = inventory_acc_id
                title = f"買入 {symbol}"
            elif t_type == "sell":
                amount = shares * price - fee
                from_acc = inventory_acc_id
                to_acc = settlement_acc_id
                title = f"賣出 {symbol}"
            elif t_type == "dividend":
                amount = price # 這裡的 price 是股利總額
                from_acc = inventory_acc_id
                to_acc = settlement_acc_id
                title = f"{symbol} 股利"
                
            if amount > 0 and t_type != "split":
                cursor.execute('''
                    INSERT INTO expenses (user_id, title, amount, date, category, account_id, to_account_id, type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'transfer', ?)
                ''', (user_id, title, amount, date, "股票交易", from_acc, to_acc, created_at))
            
            self._update_stock_avg(conn, stock_id)
            return cursor.lastrowid

    def delete_transaction(self, user_id: int, tx_id: int) -> bool:
        with get_db() as conn:
            cursor = conn.cursor()
            tx = cursor.execute("SELECT stock_id, created_at FROM stock_transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)).fetchone()
            if not tx: return False
            stock_id = tx['stock_id']
            created_at = tx['created_at']
            
            # Check if it is the latest transaction for this stock
            latest = cursor.execute("SELECT id FROM stock_transactions WHERE stock_id = ? AND user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (stock_id, user_id)).fetchone()
            if latest and latest['id'] != tx_id:
                raise ValueError("只能刪除最上層（最新）的交易紀錄")
                
            cursor.execute("DELETE FROM stock_transactions WHERE id = ?", (tx_id,))
            cursor.execute("DELETE FROM expenses WHERE user_id = ? AND category = '股票交易' AND created_at = ?", (user_id, created_at))
            
            self._update_stock_avg(conn, stock_id)
            return True

    def update_transaction(self, user_id: int, tx_id: int, date: str, shares: float, price: float, fee: float, note: str) -> bool:
        shares = int(shares)
        with get_db() as conn:
            cursor = conn.cursor()
            tx = cursor.execute("SELECT stock_id, type, created_at FROM stock_transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)).fetchone()
            if not tx: return False
            stock_id = tx['stock_id']
            t_type = tx['type']
            created_at = tx['created_at']
            
            # Check if it is the latest
            latest = cursor.execute("SELECT id FROM stock_transactions WHERE stock_id = ? AND user_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (stock_id, user_id)).fetchone()
            if latest and latest['id'] != tx_id:
                raise ValueError("只能修改最上層（最新）的交易紀錄")
                
            cursor.execute('''
                UPDATE stock_transactions 
                SET date = ?, shares = ?, price = ?, fee = ?, note = ?
                WHERE id = ?
            ''', (date, shares, price, fee, note, tx_id))
            
            amount = 0
            if t_type == "buy": amount = shares * price + fee
            elif t_type == "sell": amount = shares * price - fee
            elif t_type == "dividend": amount = price
            
            if amount > 0 and t_type != "split":
                cursor.execute('''
                    UPDATE expenses
                    SET amount = ?, date = ?
                    WHERE user_id = ? AND category = '股票交易' AND created_at = ?
                ''', (amount, date, user_id, created_at))
                
            self._update_stock_avg(conn, stock_id)
            return True

    def update_prices(self, user_id: int):
        stocks = self.get_by_user(user_id)
        if not stocks: return True

        # 建立原始代碼與 yfinance 代碼的對照表
        symbol_map = {}
        for s in stocks:
            original = s['symbol']
            # 若 ticker 只含數字或 5 碼數字開頭 → 視為台股
            if original.isdigit() or re.match(r'^\d{5}', original):
                symbol_map[original] = f"{original}.TW"
            else:
                symbol_map[original] = original

        yf_symbols = list(set(symbol_map.values()))
        
        try:
            # 一次 batch 載入所有 ticker
            tickers = yf.Tickers(" ".join(yf_symbols))

            with get_db() as conn:
                cursor = conn.cursor()
                updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for s in stocks:
                    orig_sym = s['symbol']
                    yf_sym = symbol_map[orig_sym]
                    
                    price = None
                    try:
                        # 確保：yfinance 取價使用 info["regularMarketPrice"]
                        info = tickers.tickers[yf_sym].info
                        price = info.get("regularMarketPrice")
                        
                        # 備用方案
                        if price is None:
                            price = info.get("currentPrice") or info.get("previousClose")
                        
                        if price is not None and not math.isnan(float(price)):
                            cursor.execute("UPDATE stocks SET current_price = ?, updated_at = ? WHERE id = ?", (float(price), updated_at, s['id']))
                    except Exception as parse_e:
                        print(f"Error parsing price for {orig_sym}: {parse_e}")
                        continue
            return True
        except Exception as e:
            print(f"Error updating prices: {e}")
            return False
