---
name: verify
description: 啟動 expense_tracker 並以 Playwright 驅動頁面驗證變更（隔離 DATA_DIR、不動真實資料與 5000 埠）
---

# 驗證 expense_tracker 變更

## 啟動（不要直接跑 run.py）

`run.py` 會強殺占用 5000 埠的程序，且預設 DATA_DIR 是 `app/data/`（真實使用者資料）。
驗證時用獨立埠 + 隔離資料夾：

```python
# serve_verify.py — 放 scratchpad，背景執行
import os, sys
sys.path.insert(0, r"c:\My Codes\Vibe Coding\expense_tracker")
os.chdir(r"c:\My Codes\Vibe Coding\expense_tracker")
import config
config.Config.DATA_DIR = os.path.abspath("verify_data")  # 隔離，勿用預設
from app.views import create_app
create_app().run(host="127.0.0.1", port=5599, debug=False)
```

## 驅動（Python Playwright 已安裝，chromium 可用）

- 無 cookie 的新 context = 全新空裝置，任何頁面都會導回 `/onboarding`。
  先 `page.goto('/onboarding')` 再用 `ctx.request.post('/api/onboarding/fresh')`
  種預設資料（request context 與瀏覽器共用 device_id cookie）。
- 建測試資料直接打 API：`POST /api/groups`、`POST /api/categories`（JSON body）。
- 主頁 `/` 是 iframe shell（home/charts/stocks/debts/settings 五個分頁常駐）；
  各分頁也可單獨開 `/home?embed=1`、`/charts?embed=1` 直接測。
  iframe 用 `page.frames` 依 url 找，`frame.evaluate(...)` 操作。
- 篩選下拉選單（`.mfilter-menu`）平常隱藏：`wait_for_selector(..., state="attached")`；
  點選項前先點開對應按鈕（charts：`#mf-btn-grp`；home 進階篩選：先
  `#adv-filter-btn` 開 overlay，再 `#adv-grp-btn` 開下拉）。
- 掛 `page.on("pageerror", ...)` 收 JS 錯誤，結束時一併檢查。

## 事後清理

```bash
netstat -ano | grep :5599 | grep LISTENING  # 找 PID 後 taskkill //F //PID <pid>
```
