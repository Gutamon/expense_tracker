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

**Per-device identity, no login (yet).** There is no account system or password. Each device is a self-contained user, identified by a signed `device_id` cookie. `app/models/user.py` is the single seam that resolves "who is this request" (`resolve_device_id`, `adopt_or_create`, `user_data_dir`) and records devices in `DATA_DIR/users/registry.csv`. The first device to connect after upgrade **adopts** the existing shared CSVs (moved into its folder); every later device starts fresh. `csv_store.is_first_run()` (empty per-device `accounts.csv`) redirects to `/onboarding`. Future login / cloud sync / shared ledgers plug in here (e.g. map `device_id → account_id` in `registry.csv`) without touching models.

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
