from app.models.db import get_db

class CategoryModel:
    DEFAULT_CATEGORIES = [
        {"name": "餐飲", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "交通", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "娛樂", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "休閒"},
        {"name": "購物", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "醫療", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "健康"},
        {"name": "住宿", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "教育", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "學習"},
        {"name": "薪水", "type": "income", "is_asset": 1, "in_budget": 0, "group_name": "主要收入"},
        {"name": "獎金", "type": "income", "is_asset": 1, "in_budget": 0, "group_name": "額外收入"},
        {"name": "其他", "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "其他"}
    ]

    def create_defaults(self, user_id):
        with get_db() as conn:
            cursor = conn.cursor()

            # 建立預設群組 (name, type)
            default_groups = [
                ("生活", "expense"), ("休閒", "expense"), ("健康", "expense"),
                ("學習", "expense"), ("主要收入", "income"), ("額外收入", "income"), ("其他", "expense")
            ]
            for i, (gname, gtype) in enumerate(default_groups):
                cursor.execute(
                    "INSERT INTO category_groups (user_id, name, sort_order, type) VALUES (?, ?, ?, ?)",
                    (user_id, gname, i, gtype)
                )
                
            # 建立預設類別
            for i, cat in enumerate(self.DEFAULT_CATEGORIES):
                cursor.execute(
                    "INSERT INTO categories (user_id, name, type, is_asset, in_budget, group_name, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                    (user_id, cat["name"], cat["type"], cat["is_asset"], cat["in_budget"], cat["group_name"], i)
                )

    def get_by_user(self, user_id):
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM categories WHERE user_id = ? ORDER BY sort_order, id", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def create(self, user_id, name, type="expense", is_asset=1, in_budget=1, group_name=""):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO categories (user_id, name, type, is_asset, in_budget, group_name, sort_order) VALUES (?, ?, ?, ?, ?, ?, 99)", 
                (user_id, name, type, int(is_asset), int(in_budget), group_name)
            )
            return cursor.lastrowid

    def update(self, cat_id, user_id, name, type="expense", is_asset=1, in_budget=1, group_name=""):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE categories SET name = ?, type = ?, is_asset = ?, in_budget = ?, group_name = ? WHERE id = ? AND user_id = ?", 
                (name, type, int(is_asset), int(in_budget), group_name, cat_id, user_id)
            )
            return cursor.rowcount > 0
            
    def update_sort_orders(self, user_id, id_order_list):
        with get_db() as conn:
            cursor = conn.cursor()
            for order, item_id in enumerate(id_order_list):
                cursor.execute("UPDATE categories SET sort_order = ? WHERE id = ? AND user_id = ?", (order, item_id, user_id))
            return True

    def delete(self, cat_id, user_id, replace_with_id=None):
        with get_db() as conn:
            cursor = conn.cursor()
            if replace_with_id:
                old_row = cursor.execute("SELECT name FROM categories WHERE id = ? AND user_id = ?", (cat_id, user_id)).fetchone()
                new_row = cursor.execute("SELECT name FROM categories WHERE id = ? AND user_id = ?", (replace_with_id, user_id)).fetchone()
                if old_row and new_row:
                    cursor.execute("UPDATE expenses SET category = ? WHERE category = ? AND user_id = ?", (new_row['name'], old_row['name'], user_id))

            cursor.execute("DELETE FROM categories WHERE id = ? AND user_id = ?", (cat_id, user_id))
            return cursor.rowcount > 0

    def update_budget(self, cat_id, user_id, monthly_budget):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE categories SET monthly_budget = ? WHERE id = ? AND user_id = ?", (float(monthly_budget), cat_id, user_id))
            return cursor.rowcount > 0

class CategoryGroupModel:
    def get_by_user(self, user_id):
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM category_groups WHERE user_id = ? ORDER BY sort_order, id", (user_id,)).fetchall()
            return [dict(r) for r in rows]
            
    def create(self, user_id, name, type='expense'):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO category_groups (user_id, name, sort_order, type) VALUES (?, ?, 99, ?)", (user_id, name, type))
            return cursor.lastrowid

    def update(self, group_id, user_id, name, type=None):
        with get_db() as conn:
            cursor = conn.cursor()
            old_row = cursor.execute("SELECT name FROM category_groups WHERE id = ? AND user_id = ?", (group_id, user_id)).fetchone()
            if not old_row: return False
            old_name = old_row["name"]

            if type is not None:
                cursor.execute("UPDATE category_groups SET name = ?, type = ? WHERE id = ? AND user_id = ?", (name, type, group_id, user_id))
            else:
                cursor.execute("UPDATE category_groups SET name = ? WHERE id = ? AND user_id = ?", (name, group_id, user_id))
            updated = cursor.rowcount > 0

            if old_name != name:
                cursor.execute("UPDATE categories SET group_name = ? WHERE group_name = ? AND user_id = ?", (name, old_name, user_id))

            return updated
            
    def update_sort_orders(self, user_id, id_order_list):
        with get_db() as conn:
            cursor = conn.cursor()
            for order, item_id in enumerate(id_order_list):
                cursor.execute("UPDATE category_groups SET sort_order = ? WHERE id = ? AND user_id = ?", (order, item_id, user_id))
            return True
            
    def delete(self, group_id, user_id):
        with get_db() as conn:
            cursor = conn.cursor()
            # 刪除前先把底下的類別 group_name 設為未分類
            old_row = cursor.execute("SELECT name FROM category_groups WHERE id = ? AND user_id = ?", (group_id, user_id)).fetchone()
            if old_row:
                cursor.execute("UPDATE categories SET group_name = '未分類' WHERE group_name = ? AND user_id = ?", (old_row["name"], user_id))
            cursor.execute("DELETE FROM category_groups WHERE id = ? AND user_id = ?", (group_id, user_id))
            return cursor.rowcount > 0