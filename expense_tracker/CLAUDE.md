# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

```bash
python run.py
```

Runs on `http://0.0.0.0:5000` with debug mode enabled. The app uses SQLite — the database file is `DataBase.db` at the project root.

## Tech Stack

- **Backend**: Flask (blueprints, app factory pattern)
- **Database**: SQLite3 via raw `sqlite3` module (no ORM)
- **Auth**: `werkzeug.security` for password hashing; Flask sessions
- **Stock data**: `yfinance`
- **Frontend**: Vanilla JS, Jinja2 templates, custom dark CSS

## Architecture

### App Factory

`app/views/__init__.py` — `create_app()` initializes Flask, loads `config.py`, calls `init_db()`, registers all four blueprints, and adds a `Cache-Control: no-store` after-request hook.

### Blueprints

| Blueprint | File | Prefix |
|-----------|------|--------|
| `auth_bp` | `app/controllers/auth_routes.py` | (none) |
| `main_bp` | `app/controllers/main_routes.py` | (none) |
| `settings_bp` | `app/controllers/category_routes.py` | (none) |
| `stock_bp` | `app/controllers/stock_routes.py` | (none) |

### Database Layer

All DB access is raw SQL via context managers in `app/models/db.py`. Each model file (`expense.py`, `category.py`, `account.py`, `stock.py`, `user.py`) contains query functions — there are no ORM models. `init_db()` in `db.py` creates all tables and inserts default categories/accounts for new users.

### Tables

`users`, `categories`, `category_groups`, `expenses`, `accounts`, `stocks`, `stock_transactions`

Transfer transactions create two `expenses` rows (debit + credit) linked by matching `note` values. Stock buy/sell also writes into `expenses` for account balance tracking.

### Session & Auth

All routes check `session['user_id']` — unauthenticated requests redirect to `/login`. No Flask-Login; session management is manual.

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
- `user_id` is always scoped per query — never fetch data without filtering by the session user.
- `sort_order` columns control display order; drag-to-reorder uses PATCH endpoints.
- Stock prices are fetched live from yfinance on the stocks page and cached in the `stocks` table.
