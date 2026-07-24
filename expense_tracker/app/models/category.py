from app.models.csv_store import read_csv, write_csv, next_id, SCHEMA


class CategoryModel:
    DEFAULT_CATEGORIES = [
        {"name": "餐飲",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "交通",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "娛樂",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "休閒"},
        {"name": "購物",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "醫療",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "健康"},
        {"name": "住宿",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "生活"},
        {"name": "教育",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "學習"},
        {"name": "薪水",  "type": "income",  "is_asset": 1, "in_budget": 0, "group_name": "主要收入"},
        {"name": "獎金",  "type": "income",  "is_asset": 1, "in_budget": 0, "group_name": "額外收入"},
        {"name": "其他",  "type": "expense", "is_asset": 1, "in_budget": 1, "group_name": "其他"},
    ]

    # 系統類別：由功能模組（股票交易等）自動產生的類別，不可改名/刪除，
    # 但使用者仍可調整是否計入預算（支出類）。以 (name, type, is_system) 判斷是否已存在，
    # 缺少時自動補上，讓既有帳本升級後也能補齊。
    SYSTEM_CATEGORIES = [
        {"name": "股票交易", "type": "expense", "is_asset": 1, "in_budget": 0, "group_name": "投資"},
        {"name": "股票交易", "type": "income", "is_asset": 1, "in_budget": 0, "group_name": "投資"},
    ]

    def create_defaults(self):
        group_model = CategoryGroupModel()
        group_model.create_defaults()

        rows = read_csv("categories.csv")
        for i, cat in enumerate(self.DEFAULT_CATEGORIES):
            new_id = next_id(rows)
            rows.append({
                "id": new_id,
                "name": cat["name"],
                "type": cat["type"],
                "is_asset": cat["is_asset"],
                "in_budget": cat["in_budget"],
                "group_name": cat["group_name"],
                "sort_order": i,
                "monthly_budget": 0,
                "is_system": 0,
            })
        write_csv("categories.csv", rows, SCHEMA["categories.csv"])
        self.ensure_system_categories()

    def ensure_system_categories(self) -> dict:
        """補齊系統類別（目前僅股票交易），回傳 {type: category_id}。已存在則不動。"""
        CategoryGroupModel().ensure_system_groups()
        rows = read_csv("categories.csv")
        result = {}
        changed = False
        for cat in self.SYSTEM_CATEGORIES:
            existing = next((r for r in rows if r.get("name") == cat["name"]
                             and r.get("type") == cat["type"] and int(r.get("is_system") or 0)), None)
            if existing:
                result[cat["type"]] = int(existing["id"])
                continue
            new_id = next_id(rows)
            rows.append({
                "id": new_id,
                "name": cat["name"],
                "type": cat["type"],
                "is_asset": cat["is_asset"],
                "in_budget": cat["in_budget"],
                "group_name": cat["group_name"],
                "sort_order": 99,
                "monthly_budget": 0,
                "is_system": 1,
            })
            result[cat["type"]] = new_id
            changed = True
        if changed:
            write_csv("categories.csv", rows, SCHEMA["categories.csv"])
        return result

    def get_all(self) -> list:
        self.ensure_system_categories()
        rows = read_csv("categories.csv")
        rows.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
        return rows

    def create(self, name, type="expense", is_asset=1, in_budget=1, group_name="") -> int:
        rows = read_csv("categories.csv")
        new_id = next_id(rows)
        rows.append({
            "id": new_id,
            "name": name,
            "type": type,
            "is_asset": int(is_asset),
            "in_budget": int(in_budget),
            "group_name": group_name,
            "sort_order": 99,
            "monthly_budget": 0,
        })
        write_csv("categories.csv", rows, SCHEMA["categories.csv"])
        return new_id

    def update(self, cat_id, name, type="expense", is_asset=1, in_budget=1, group_name="") -> bool:
        rows = read_csv("categories.csv")
        cat_id = str(cat_id)
        old_name = None
        for r in rows:
            if str(r.get("id")) == cat_id:
                if int(r.get("is_system") or 0):
                    # 系統類別：只允許調整是否計預算，名稱/群組/收支類型固定不可改。
                    r["in_budget"] = int(in_budget)
                    write_csv("categories.csv", rows, SCHEMA["categories.csv"])
                    return True
                old_name = r["name"]
                r["name"] = name
                r["type"] = type
                r["is_asset"] = int(is_asset)
                r["in_budget"] = int(in_budget)
                r["group_name"] = group_name
                write_csv("categories.csv", rows, SCHEMA["categories.csv"])
                break
        if old_name is None:
            return False

        # Refresh the denormalized category name cached on rows bound to this id, so
        # exports/legacy readers see the new name too. Display already resolves live
        # by id, so this is just keeping the cached copy honest — only rewrite when
        # the name actually changed.
        if name != old_name:
            self._rename_cached_name(int(cat_id), name)
        return True

    @staticmethod
    def _rename_cached_name(cat_id: int, new_name: str):
        for fname in ("expenses.csv", "monthly_history.csv"):
            data = read_csv(fname)
            changed = False
            for r in data:
                if int(r.get("category_id") or 0) == cat_id and r.get("category") != new_name:
                    r["category"] = new_name
                    changed = True
            if changed:
                write_csv(fname, data, SCHEMA[fname])

    def update_sort_orders(self, id_order_list) -> bool:
        rows = read_csv("categories.csv")
        order_map = {str(item_id): i for i, item_id in enumerate(id_order_list)}
        for r in rows:
            if str(r.get("id")) in order_map:
                r["sort_order"] = order_map[str(r["id"])]
        write_csv("categories.csv", rows, SCHEMA["categories.csv"])
        return True

    def delete(self, cat_id, replace_with_id=None) -> bool:
        rows = read_csv("categories.csv")
        cat_id = str(cat_id)
        old = next((r for r in rows if str(r.get("id")) == cat_id), None)
        if old is None:
            return False
        if int(old.get("is_system") or 0):
            return False
        old_name = old["name"]

        if replace_with_id:
            target = next((r for r in rows if str(r.get("id")) == str(replace_with_id)), None)
            if target:
                new_name, new_id = target["name"], int(target["id"])
                # Reassign by id when the row carries one (post-migration), else by
                # the legacy name match. Update both id and cached name together.
                exp_rows = read_csv("expenses.csv")
                for e in exp_rows:
                    matches = (int(e.get("category_id") or 0) == int(cat_id)) or \
                              (not int(e.get("category_id") or 0) and e.get("category") == old_name)
                    if matches:
                        e["category"] = new_name
                        e["category_id"] = new_id
                write_csv("expenses.csv", exp_rows, SCHEMA["expenses.csv"])

                hist_rows = read_csv("monthly_history.csv")
                changed = False
                for h in hist_rows:
                    matches = (int(h.get("category_id") or 0) == int(cat_id)) or \
                              (not int(h.get("category_id") or 0) and h.get("category") == old_name)
                    if matches:
                        h["category"] = new_name
                        h["category_id"] = new_id
                        changed = True
                if changed:
                    write_csv("monthly_history.csv", hist_rows, SCHEMA["monthly_history.csv"])

        rows = [r for r in rows if str(r.get("id")) != cat_id]
        write_csv("categories.csv", rows, SCHEMA["categories.csv"])
        return True

    def update_budget(self, cat_id, monthly_budget) -> bool:
        rows = read_csv("categories.csv")
        cat_id = str(cat_id)
        for r in rows:
            if str(r.get("id")) == cat_id:
                r["monthly_budget"] = float(monthly_budget)
                write_csv("categories.csv", rows, SCHEMA["categories.csv"])
                return True
        return False


class CategoryGroupModel:
    DEFAULT_GROUPS = [
        ("生活", "expense"), ("休閒", "expense"), ("健康", "expense"),
        ("學習", "expense"), ("主要收入", "income"), ("額外收入", "income"), ("其他", "expense"),
    ]

    # 系統群組：承載系統類別（目前為股票交易）的固定群組，不可改名/刪除。
    SYSTEM_GROUPS = [("投資", "expense"), ("投資", "income")]

    def create_defaults(self):
        rows = read_csv("category_groups.csv")
        for i, (gname, gtype) in enumerate(self.DEFAULT_GROUPS):
            new_id = next_id(rows)
            rows.append({"id": new_id, "name": gname, "sort_order": i, "type": gtype, "is_system": 0})
        write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])
        self.ensure_system_groups()

    def ensure_system_groups(self):
        """補齊系統群組（目前僅投資）。已存在則不動。"""
        rows = read_csv("category_groups.csv")
        changed = False
        for gname, gtype in self.SYSTEM_GROUPS:
            existing = next((r for r in rows if r.get("name") == gname
                             and r.get("type") == gtype and int(r.get("is_system") or 0)), None)
            if existing:
                continue
            new_id = next_id(rows)
            rows.append({"id": new_id, "name": gname, "sort_order": 99, "type": gtype, "is_system": 1})
            changed = True
        if changed:
            write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])

    def get_all(self) -> list:
        self.ensure_system_groups()
        rows = read_csv("category_groups.csv")
        rows.sort(key=lambda r: (int(r.get("sort_order") or 0), int(r.get("id") or 0)))
        return rows

    def create(self, name, type="expense") -> int:
        rows = read_csv("category_groups.csv")
        new_id = next_id(rows)
        rows.append({"id": new_id, "name": name, "sort_order": 99, "type": type, "is_system": 0})
        write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])
        return new_id

    def update(self, group_id, name, type=None) -> bool:
        rows = read_csv("category_groups.csv")
        group_id = str(group_id)
        old_name = None
        for r in rows:
            if str(r.get("id")) == group_id:
                if int(r.get("is_system") or 0):
                    return False
                old_name = r["name"]
                r["name"] = name
                if type is not None:
                    r["type"] = type
                break
        if old_name is None:
            return False
        write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])

        if old_name != name:
            cat_rows = read_csv("categories.csv")
            for c in cat_rows:
                if c.get("group_name") == old_name:
                    c["group_name"] = name
            write_csv("categories.csv", cat_rows, SCHEMA["categories.csv"])
        return True

    def update_sort_orders(self, id_order_list) -> bool:
        rows = read_csv("category_groups.csv")
        order_map = {str(item_id): i for i, item_id in enumerate(id_order_list)}
        for r in rows:
            if str(r.get("id")) in order_map:
                r["sort_order"] = order_map[str(r["id"])]
        write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])
        return True

    def delete(self, group_id) -> bool:
        rows = read_csv("category_groups.csv")
        group_id = str(group_id)
        target = next((r for r in rows if str(r.get("id")) == group_id), None)
        if target is None:
            return False
        if int(target.get("is_system") or 0):
            return False
        old_name = target["name"]
        if old_name:
            cat_rows = read_csv("categories.csv")
            for c in cat_rows:
                if c.get("group_name") == old_name:
                    c["group_name"] = "未分類"
            write_csv("categories.csv", cat_rows, SCHEMA["categories.csv"])
        rows = [r for r in rows if str(r.get("id")) != group_id]
        write_csv("category_groups.csv", rows, SCHEMA["category_groups.csv"])
        return True
