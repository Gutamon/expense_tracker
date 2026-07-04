from datetime import datetime
from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA
from app.models.expense import ExpenseModel
from app.models.account import AccountModel

expense_model = ExpenseModel()


class StockModel:
    def get_all(self) -> list:
        return read_csv("stocks.csv")

    def get_transactions(self, stock_id: int = None) -> list:
        txs = read_csv("stock_transactions.csv")
        if stock_id:
            txs = [t for t in txs if str(t.get("stock_id")) == str(stock_id)]
        stocks = {str(s["id"]): s for s in read_csv("stocks.csv")}
        for t in txs:
            s = stocks.get(str(t.get("stock_id")), {})
            t["symbol"] = s.get("symbol", "")
            t["name"] = s.get("name", "")
        txs.sort(key=lambda t: (t.get("date", ""), t.get("id", "")), reverse=True)
        return txs

    def create_position(self, symbol: str, name: str, account_id: int):
        rows = read_csv("stocks.csv")
        if any(r.get("symbol") == symbol for r in rows):
            return False
        new_id = next_id(rows)
        rows.append({
            "id": new_id,
            "symbol": symbol,
            "name": name,
            "shares": 0,
            "avg_price": 0,
            "current_price": 0,
            "updated_at": "",
            "account_id": account_id,
        })
        write_csv("stocks.csv", rows, SCHEMA["stocks.csv"])
        return new_id

    def update_price(self, stock_id: int, price: float) -> bool:
        rows = read_csv("stocks.csv")
        stock_id = str(stock_id)
        for r in rows:
            if str(r.get("id")) == stock_id:
                r["current_price"] = float(price)
                r["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                write_csv("stocks.csv", rows, SCHEMA["stocks.csv"])
                return True
        return False

    def _update_stock_avg(self, stock_id):
        txs = read_csv("stock_transactions.csv")
        txs = [t for t in txs if str(t.get("stock_id")) == str(stock_id)]
        txs.sort(key=lambda t: (t.get("date", ""), t.get("id", "")))

        shares = 0.0
        total_cost = 0.0
        for t in txs:
            t_type = t.get("type")
            t_shares = float(t.get("shares") or 0)
            t_price = float(t.get("price") or 0)
            if t_type == "buy":
                shares += t_shares
                total_cost += t_shares * t_price
            elif t_type == "sell":
                if shares > 0:
                    avg_cost = total_cost / shares
                    total_cost -= t_shares * avg_cost
                shares -= t_shares
                if shares <= 0:
                    shares = 0
                    total_cost = 0
            elif t_type == "split":
                shares = shares * t_price

        shares = int(round(shares))
        avg_price = (total_cost / shares) if shares > 0 else 0

        stock_rows = read_csv("stocks.csv")
        for r in stock_rows:
            if str(r.get("id")) == str(stock_id):
                r["shares"] = shares
                r["avg_price"] = round(avg_price, 4)
                break
        write_csv("stocks.csv", stock_rows, SCHEMA["stocks.csv"])

    def add_transaction(self, stock_id: int, t_type: str, date: str, shares: float,
                        price: float, fee: float, note: str):
        shares = int(shares)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        stock_rows = read_csv("stocks.csv")
        stock = next((r for r in stock_rows if str(r.get("id")) == str(stock_id)), None)
        if not stock:
            return None
        settlement_acc_id = stock.get("account_id", 0)
        symbol = stock.get("symbol", "")

        tx_rows = read_csv("stock_transactions.csv")
        tx_id = next_id(tx_rows)
        tx_rows.append({
            "id": tx_id,
            "stock_id": stock_id,
            "type": t_type,
            "date": date,
            "shares": shares,
            "price": price,
            "fee": fee,
            "note": note or "",
            "created_at": created_at,
        })
        write_csv("stock_transactions.csv", tx_rows, SCHEMA["stock_transactions.csv"])

        amount = 0
        exp_type = None
        title = ""
        if t_type == "buy":
            amount = shares * price + fee
            exp_type = "expense"
            title = f"買入 {symbol}"
        elif t_type == "sell":
            amount = shares * price - fee
            exp_type = "income"
            title = f"賣出 {symbol}"
        elif t_type == "dividend":
            amount = price
            exp_type = "income"
            title = f"{symbol} 股利"

        if amount > 0 and exp_type:
            expense_model.create_with_links(
                title=title, amount=amount, category="股票交易",
                date=date, note=note or "", type=exp_type,
                account_id=int(settlement_acc_id),
                stock_transaction_id=tx_id,
            )

        self._update_stock_avg(stock_id)
        return tx_id

    def delete_transaction(self, tx_id: int) -> bool:
        tx_rows = read_csv("stock_transactions.csv")
        tx_id = str(tx_id)
        tx = next((t for t in tx_rows if str(t.get("id")) == tx_id), None)
        if not tx:
            return False
        stock_id = tx["stock_id"]

        latest = max(
            (t for t in tx_rows if str(t.get("stock_id")) == str(stock_id)),
            key=lambda t: (t.get("created_at", ""), t.get("id", "")),
            default=None
        )
        if latest and str(latest.get("id")) != tx_id:
            raise ValueError("只能刪除最上層（最新）的交易紀錄")

        tx_rows = [t for t in tx_rows if str(t.get("id")) != tx_id]
        write_csv("stock_transactions.csv", tx_rows, SCHEMA["stock_transactions.csv"])

        expense_model.delete_where(stock_transaction_id=tx_id)

        self._update_stock_avg(stock_id)
        return True

    def update_transaction(self, tx_id: int, date: str, shares: float, price: float,
                           fee: float, note: str) -> bool:
        shares = int(shares)
        tx_rows = read_csv("stock_transactions.csv")
        tx_id = str(tx_id)
        tx = next((t for t in tx_rows if str(t.get("id")) == tx_id), None)
        if not tx:
            return False
        stock_id = tx["stock_id"]
        t_type = tx.get("type")

        latest = max(
            (t for t in tx_rows if str(t.get("stock_id")) == str(stock_id)),
            key=lambda t: (t.get("created_at", ""), t.get("id", "")),
            default=None
        )
        if latest and str(latest.get("id")) != tx_id:
            raise ValueError("只能修改最上層（最新）的交易紀錄")

        for t in tx_rows:
            if str(t.get("id")) == tx_id:
                t["date"] = date
                t["shares"] = shares
                t["price"] = price
                t["fee"] = fee
                t["note"] = note or ""
                break
        write_csv("stock_transactions.csv", tx_rows, SCHEMA["stock_transactions.csv"])

        amount = 0
        if t_type == "buy":    amount = shares * price + fee
        elif t_type == "sell": amount = shares * price - fee
        elif t_type == "dividend": amount = price

        if amount > 0 and t_type != "split":
            updated = expense_model.update_where(
                match={"stock_transaction_id": tx_id},
                updates={"amount": amount, "date": date}
            )
            if not updated:
                expense_model.update_where(
                    match={"category": "股票交易", "stock_transaction_id": ""},
                    updates={"amount": amount, "date": date}
                )

        self._update_stock_avg(stock_id)
        return True

    def delete_position(self, stock_id: int) -> bool:
        stock_id = str(stock_id)
        tx_rows = read_csv("stock_transactions.csv")
        if any(str(t.get("stock_id")) == stock_id for t in tx_rows):
            return False
        rows = read_csv("stocks.csv")
        target = next((r for r in rows if str(r.get("id")) == stock_id), None)
        if not target:
            return False
        new_rows = [r for r in rows if str(r.get("id")) != stock_id]
        write_csv("stocks.csv", new_rows, SCHEMA["stocks.csv"])
        linked = int(target.get("linked_account_id") or 0)
        if linked:
            AccountModel().delete(linked)
        return True
