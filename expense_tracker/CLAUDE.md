# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Communication & Response Style

See [.agents/rules/answer.md](.agents/rules/answer.md) for the guiding principles on how to respond in this project. Key principles: provide concrete, actionable answers (not vague suggestions); use Traditional Chinese; be concise and natural; proactively suggest solutions beyond what's asked; treat as an experienced developer; prioritize direct answers with supporting detail; value reasoning over authority; and avoid over-explanation.

## Running the App

```bash
python run.py
```

Runs on `http://0.0.0.0:5000` with debug mode enabled. All data is stored as CSV files under the directory configured by `DATA_DIR` in `config.py` (default `app/data/`). There is no SQL database.

## Tech Stack

- **Backend**: Flask (blueprints, app factory pattern)
- **Storage**: CSV files via a custom layer in `app/models/csv_store.py` (`read_csv` / `write_csv` / `next_id` / `get_setting` / `set_setting`). No database, no ORM.
- **Stock data**: `yfinance`
- **Frontend**: Vanilla JS, Jinja2 templates, custom dark CSS

## Architecture

### App Factory

`app/views/__init__.py` — `create_app()` initializes Flask, loads `config.py`, calls `csv_store.set_data_dir()` + `csv_store.init_data_dir()` (creates any missing CSV files), registers the five blueprints, and adds a `Cache-Control: no-store` after-request hook.

### Blueprints

| Blueprint | File | Prefix |
|-----------|------|--------|
| `main_bp` | `app/controllers/main_routes.py` | (none) |
| `settings_bp` | `app/controllers/category_routes.py` | (none) |
| `stock_bp` | `app/controllers/stock_routes.py` | (none) |
| `debt_bp` | `app/controllers/debt_routes.py` | (none) |
| `onboarding_bp` | `app/controllers/onboarding_routes.py` | (none) |

### Data Layer

All data access goes through `app/models/csv_store.py` — there is no `db.py` and no SQL. `SCHEMA` defines the column order for each CSV file; `INT_FIELDS` / `FLOAT_FIELDS` drive type coercion on read. Each model file (`expense.py`, `category.py`, `account.py`, `stock.py`, `debt.py`) contains functions that read/transform/write CSV rows. Default categories/accounts are seeded on first run via the onboarding flow.

**Data is partitioned per device.** `csv_store._data_dir()` resolves the *active* directory per request from `flask.g.data_dir` (bound by the `before_request` hook in `app/views/__init__.py`), falling back to the root dir outside a request. Each device's CSVs live under `DATA_DIR/users/<device_id>/`; `init_current_user()` seeds a device's folder on first use, while startup `init_data_dir()` only ensures `DATA_DIR/users/` exists. Models are unaware of this — they just call `read_csv`/`write_csv`.

### CSV Files (SCHEMA)

`expenses`, `categories`, `category_groups`, `accounts`, `stocks`, `stock_transactions`, `loans`, `loan_payments`, `monthly_budgets`, `cat_monthly_budgets`, `settings`

A transfer is stored as a **single `expenses` row** with `type='transfer'`, `account_id` (from), `to_account_id` (to), and optional `to_amount` (cross-currency). Stock buy/sell and loan/credit-card repayments also write into `expenses` for account-balance tracking, linked via `stock_transaction_id` / `loan_id` / `loan_payment_id`.

### Session & Auth

**Per-device identity, no login.** There is no account system or password. Each device is a self-contained user, identified by a signed `device_id` cookie. `app/models/user.py` is the single seam that resolves "who is this request" (`resolve_device_id`, `adopt_or_create`, `user_data_dir`) and records devices in `DATA_DIR/users/registry.csv`. A cookie-less request always gets a **brand new, empty device** — `adopt_or_create` deliberately never re-adopts an existing device's data on a missing cookie, because on a fixed public URL (ngrok) that would expose one user's ledger to the next visitor. `csv_store.is_first_run()` (empty per-device `accounts.csv`) shows `/onboarding`. Future login / cloud sync / shared ledgers plug in here (e.g. map `device_id → account_id` in `registry.csv`) without touching models.

**識別碼 (sync codes)** serve a dual role: recover a lost cookie *and* sync multiple devices onto one ledger. A code identifies a **shared ledger folder** (a `sync_id`), not a single device — so entering it on a second device makes both read/write the same data. It's minted lazily: a device only gets a code (and its own folder gets promoted to a `sync_id`-named shared folder via `_promote_to_sync_group`) when the user first reveals it on `/settings` (`POST /api/sync-code/ensure` → `user.ensure_sync_code`). `settings.html` render only *reads* an existing code (`user.sync_code_if_exists`, never promotes — see [[project_sync_promote_iframe_race]]). Codes live in `DATA_DIR/users/sync_codes.csv` (`code,sync_id,created_at`). Submitting one on the onboarding screen — reliably via the top-level navigation `GET /onboarding/join?code=…` (`_do_join` → `resolve_sync_code` → `join_sync_group`), whose `Set-Cookie` rides a real document response so iOS commits it; the `POST /api/onboarding/join-by-code` XHR only validates — resolves it to the `sync_id` and attaches this browser's `device_id` to that group. Regenerating (`POST /api/sync-code/regenerate`) invalidates the previous code. Treat a code as a bearer secret — anyone who has it can access that ledger. The ZIP export in 設定 remains the fallback if a folder is ever lost outright. See **主/從裝置角色** below for owner/member roles layered on top of this.

**主/從裝置角色.** A sync group has one **owner (主裝置)** — the device that originally minted the group via `_promote_to_sync_group` — and zero or more **members (從裝置)** that joined by entering the group's 識別碼. `registry.csv` carries a `role` column (`owner`/`member`; blank on pre-role rows, always read as `owner` via `(row.get("role") or "owner")`, so legacy CSVs need no migration). `user.is_owner` drives both UI and wipe behavior. There is still a **single 識別碼** per group (not one per device): a member joining is just `join_sync_group` flipping its `role` to `member` and pointing its `sync_id` at the owner's folder; regenerating the code doesn't eject already-joined members. On `/settings` the owner sees a **共享裝置名單** button (`GET /api/sync-code/members` → `user.group_members`) listing every device's short id + role, and can **移除** any member (`POST /api/sync-code/kick` → `user.kick_device`) — which only detaches that one device (`sync_id` cleared, `role` back to `owner`, lands on its own empty folder → re-onboards); the 識別碼 stays valid and other members are untouched. **Differentiated wipe** (`POST /api/data/wipe`): a **member** wiping means "leave the share" — just `leave_sync_group(self)`, the owner's ledger and other members unaffected, and the member's client skips the ZIP export (the ledger lives on the owner). An **owner** wiping destroys the shared ledger for everyone — clears every CSV and `clear_sync_code` (invalidates the 識別碼 and detaches all members), so members fall back to onboarding on their next request (their stale `localStorage` sync_code auto-recover bounces off the now-dead code via `?join_error=1`, no loop).

**iOS home-screen PWA quirks are worked around, not fixed at the source.** iOS routinely drops the httponly `device_id` cookie between cold launches of a standalone PWA, which would otherwise make the app "start over" every open. Mitigations: (1) the 識別碼 is mirrored into `localStorage` (`sync_code`) on every authenticated page load (`shell.html`, `settings.html`) — but never as a blank, so a previously-saved code isn't clobbered before the device has minted one; (2) the onboarding screen's `autoRecover()` reads it and silently re-attaches via the top-level `GET /onboarding/join?code=…` navigation before showing the chooser; (3) the device cookie is set `Secure` when the request arrived over HTTPS (detected via `X-Forwarded-Proto` so it works behind ngrok), which persists more reliably on iOS. **Loop-prevention invariant:** an owner wiping (`/api/data/wipe`) must also `user.clear_sync_code` — otherwise `autoRecover` re-attaches to the now-empty folder, which is first-run, which shows onboarding, which auto-recovers again… a permanent blank (the page is hidden during the attempt). The invariant holds because a dead code makes `GET /onboarding/join` bounce back to `/onboarding?join_error=1`, which clears the stale saved code and skips `autoRecover` that load. `autoRecover` additionally guards with a once-per-session `sessionStorage` flag and a 4s failsafe that always restores visibility. Separately, **file downloads must never navigate the page or `window.open`** in a standalone PWA — that backgrounds the app and freezes its JS timers, leaving buttons stuck. Fetch the file as a blob and hand it off via the Web Share API (or a temporary `<a download>` fallback) instead (`downloadBlob()` in `settings.html`, used by both export and the wipe flow).

The app is also an installable **PWA**: `manifest.json` + icons under `app/views/static/`, a service worker template at `app/views/templates/sw.js` served from root scope via the `/sw.js` route (`main_routes.py`, with `Service-Worker-Allowed: /`) and registered in the three standalone entry templates (`base.html`, `shell.html`, `onboarding.html`). The SW gives an offline app shell but never caches `/api/` responses (live data).

**Cache-busting is automatic.** `/sw.js`'s embedded `VERSION` is `main_routes._assets_version()` — the latest mtime across every file in `templates/` and `static/`, recomputed on each request. Any code change (route, template, or CSS) therefore changes `sw.js`'s bytes, so the browser detects a new service worker, installs it, and its `activate` handler deletes every older cache — no manual version bump on deploy. The registration script in each entry template also listens for `controllerchange` and reloads once, so an already-open installed PWA picks up the update instead of silently staying stale.

## Design System

Defined via CSS in the templates (deep-dark theme):

- **Background**: `#0f0f11`, surface: `#18181c`
- **Accent (income/positive)**: neon yellow-green `#c8f04a`
- **Danger (expense/negative)**: `#ff5f5f`
- **Fonts**: Noto Sans TC (UI), DM Mono (numbers/amounts)
- **Max layout width**: 960px; breakpoint at 768px

## Default Data on Registration

New users get default categories in Chinese (餐飲, 交通, 薪水, etc.), default category groups (生活, 休閒, etc.), and five default accounts (現金, 銀行, 儲值支付, 信用卡, 其他).

## Key Conventions

- All API endpoints return JSON; page routes return rendered templates.
- `sort_order` columns control display order; drag-to-reorder posts to `POST /api/.../sort` endpoints.
- Stock prices are fetched live from yfinance on the stocks page and cached in `stocks.csv`.
- Credit cards (`accounts.type == 'liability'`) carry billing fields: `billing_start_day`, `payment_due_day`, `credit_limit`, `min_payment_pct`, `min_payment_floor`, `apr`. Billing-cycle figures (本期應繳 / 累計未繳 / 最低應繳 / status) are computed in `app/models/debt.py` (`_card_billing`). Revolving interest is entered manually and recorded as a `循環利息` expense on the card.
- **Never use native browser dialogs** (`alert()`, `confirm()`, `prompt()`). All popups, confirmations, and modals must be custom-designed HTML/CSS elements that match the project's dark theme.
- **Never allow user-initiated zoom.** Every page's `<meta name="viewport">` must include `user-scalable=no, maximum-scale=1.0`. In addition, `base.html` must keep the two JS touch-event listeners that block pinch-zoom (`touchmove` with >1 touch) and double-tap zoom (`touchend` within 300 ms). Chrome Android ignores the viewport attribute alone — both layers are required. Do not remove or relax either layer under any circumstance.
- **Never show scrollbars.** All scrollbars must be hidden globally via `globals.css` (`scrollbar-width: none`, `-ms-overflow-style: none`, `::-webkit-scrollbar { display: none }`). Scrolling behaviour itself should remain intact — only the visual scrollbar track must be invisible.
