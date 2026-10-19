"""Optional Yahoo quote collector. Source market time is never replaced by fetch time."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from .risk import positive


def quote_from_metadata(symbol, metadata):
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9.&_-]{0,30}\.(NS|BO)', symbol):
        raise ValueError('Yahoo collector currently supports NSE/BSE research symbols ending .NS or .BO')
    if not isinstance(metadata, dict):
        raise ValueError('Missing Yahoo chart metadata')
    if metadata.get('symbol') != symbol:
        raise ValueError('Quote symbol does not match requested instrument')
    if metadata.get('currency') != 'INR':
        raise ValueError('Only INR quotes are supported by this collector')
    timestamp = metadata.get('regularMarketTime')
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        raise ValueError('Missing source market timestamp; refusing to invent one')
    timestamp = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
    price = positive(metadata.get('regularMarketPrice'))
    return {'price': str(price), 'timestamp': timestamp, 'source': 'Yahoo Finance via yfinance',
            'symbol': symbol, 'currency': 'INR',
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'warning': 'Public data may be delayed; intended for paper testing only'}


def yahoo_quote(symbol, ticker_factory=None):
    if ticker_factory is None:
        from yfinance import Ticker
        ticker_factory = Ticker
    ticker = ticker_factory(symbol)
    # Force a fresh history request on each new object. Use metadata price AND time,
    # not the last candle close paired with an unrelated timestamp.
    ticker.history(period='1d', interval='1m', auto_adjust=False, timeout=10, raise_errors=True)
    return quote_from_metadata(symbol, ticker.get_history_metadata())


def collect(symbols, quote_fn=None):
    quote_fn = quote_fn or yahoo_quote
    quotes, errors = {}, []
    for symbol in sorted(set(symbols)):
        try:
            quotes[symbol] = quote_fn(symbol)
        except Exception as exc:
            # Do not leak vendor response bodies or credentials into diagnostics.
            errors.append({'symbol': symbol, 'error_type': type(exc).__name__,
                           'message': 'Quote unavailable; check dependency, connectivity, symbol and data entitlement'})
    return quotes, errors


def write_feed(path, quotes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
            temp = Path(f.name)
            json.dump(quotes, f, indent=2)
            f.flush()
        temp.replace(path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()
