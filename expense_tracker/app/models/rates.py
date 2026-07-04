"""Foreign-exchange rates (local-first).

Rates are stored as TWD-per-unit in settings.csv (keys ``rate_USD`` / ``rate_JPY``),
so page rendering is fast and works offline. When the device is online, the rates
can be refreshed from yfinance (``USDTWD=X`` / ``JPYTWD=X``), overwriting the local
store for subsequent use.
"""

from datetime import datetime

from app.models import csv_store

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    _YF_AVAILABLE = False

# TWD per 1 unit of the foreign currency. Reasonable fallbacks used when no local
# rate has been saved yet.
DEFAULT_RATES = {"TWD": 1.0, "USD": 31.5, "JPY": 0.21}

# Currencies we track beyond TWD, mapped to their yfinance FX symbol.
FX_SYMBOLS = {"USD": "USDTWD=X", "JPY": "JPYTWD=X"}


def get_rates() -> dict:
    """Return {currency: TWD-per-unit}, using saved local rates or defaults."""
    rates = {"TWD": 1.0}
    for cur, default in DEFAULT_RATES.items():
        if cur == "TWD":
            continue
        raw = csv_store.get_setting(f"rate_{cur}")
        try:
            rates[cur] = float(raw) if raw not in (None, "") else default
        except (ValueError, TypeError):
            rates[cur] = default
    return rates


def save_rates(rates: dict):
    """Persist the given {currency: rate} map to settings (skips TWD)."""
    for cur, val in rates.items():
        if cur == "TWD":
            continue
        try:
            csv_store.set_setting(f"rate_{cur}", float(val))
        except (ValueError, TypeError):
            continue
    csv_store.set_setting("rates_updated_at", datetime.now().strftime("%Y-%m-%d %H:%M"))


def get_updated_at() -> str:
    return csv_store.get_setting("rates_updated_at", "") or ""


def to_twd(amount: float, currency: str, rates: dict = None) -> float:
    """Convert an amount in the given currency into TWD."""
    if rates is None:
        rates = get_rates()
    return float(amount or 0) * float(rates.get(currency or "TWD", 1.0))


def refresh_rates() -> dict:
    """Fetch live FX rates from yfinance and overwrite the local store.

    Returns {"rates": <map>, "updated": bool, "updated_at": str, "failed": [cur...]}.
    Falls back to the existing local rates for any symbol that fails to fetch.
    """
    rates = get_rates()
    if not _YF_AVAILABLE:
        return {"rates": rates, "updated": False, "updated_at": get_updated_at(),
                "failed": list(FX_SYMBOLS), "error": "yfinance 未安裝"}

    failed = []
    changed = False
    for cur, symbol in FX_SYMBOLS.items():
        try:
            info = yf.Ticker(symbol).fast_info
            price = float(info.last_price or 0)
            if price > 0:
                rates[cur] = price
                changed = True
            else:
                failed.append(cur)
        except Exception:
            failed.append(cur)

    if changed:
        save_rates(rates)

    return {"rates": rates, "updated": changed, "updated_at": get_updated_at(),
            "failed": failed}
