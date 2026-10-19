"""Persistent, long-only simulator. Never submits broker orders."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from .risk import money, positive, quantity


def day():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


class PaperBroker:
    def __init__(self, path, limits, starting_cash="100000"):
        self.limits = limits
        self.db = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), cash TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY, quantity INTEGER NOT NULL, entry TEXT NOT NULL, stop TEXT NOT NULL, high TEXT NOT NULL, trailing_pct TEXT, last TEXT NOT NULL, entry_fee TEXT NOT NULL, last_ts TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, timestamp TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, pnl TEXT NOT NULL);
        """)
        self.db.execute("INSERT OR IGNORE INTO account(id,cash) VALUES(1,?)", (str(positive(starting_cash)),))

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def event(self, kind, payload, request_id=None, pnl=Decimal(0)):
        self.db.execute("INSERT INTO events(request_id,timestamp,day,kind,payload,pnl) VALUES(?,?,?,?,?,?)",
                        (request_id, datetime.now(timezone.utc).isoformat(), day(), kind, json.dumps(payload), str(pnl)))

    def duplicate(self, request_id):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A nonempty unique request ID is required")
        row = self.db.execute("SELECT payload FROM events WHERE request_id=?", (request_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def status(self):
        account = dict(self.db.execute("SELECT * FROM account").fetchone())
        positions = [dict(r) for r in self.db.execute("SELECT * FROM positions ORDER BY symbol")]
        realized = sum((money(r[0]) for r in self.db.execute("SELECT pnl FROM events WHERE day=?", (day(),))), Decimal(0))
        unrealized = sum(((money(p["last"])-money(p["entry"]))*p["quantity"] for p in positions), Decimal(0))
        return {"mode": "local_paper", "cash": account["cash"], "paused": bool(account["paused"]),
                "positions": positions, "realized_today": str(realized), "open_pnl": str(unrealized),
                "loss_guard_pnl": str(realized + unrealized)}

    def buy(self, symbol, qty, price, timestamp, stop, request_id, trailing_pct=None):
        with self.transaction():
            previous = self.duplicate(request_id)
            if previous is not None:
                return previous
            import re
            if not re.fullmatch(r"[A-Z0-9][A-Z0-9.&^_-]{0,30}(?:\.(?:NS|BO))?", symbol):
                raise ValueError("Invalid symbol")
            qty = quantity(qty)
            price = self.limits.fill(self.limits.quote(price, timestamp), "BUY")
            status = self.status()
            if status["paused"]:
                raise ValueError("Manager paused new entries")
            if any(p["symbol"] == symbol for p in status["positions"]):
                raise ValueError("Position already exists; averaging down is disabled")
            if trailing_pct is not None and not (0 < positive(trailing_pct) < 100):
                raise ValueError("Trailing percentage must be between 0 and 100")
            self.limits.entry(price, qty, stop, money(status["loss_guard_pnl"]), money(status["cash"]))
            cost = price * qty + self.limits.fee_per_order
            self.db.execute("UPDATE account SET cash=? WHERE id=1", (str(money(status["cash"])-cost),))
            self.db.execute("INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?)", (symbol, qty, str(price), str(positive(stop)), str(price),
                str(trailing_pct) if trailing_pct is not None else None, str(price), str(self.limits.fee_per_order), timestamp))
            result = {"symbol": symbol, "side": "BUY", "quantity": qty, "fill": str(price), "mode": "local_paper"}
            self.event("BUY", result, request_id, -self.limits.fee_per_order)
            return result

    def tick(self, symbol, price, timestamp, request_id):
        with self.transaction():
            previous = self.duplicate(request_id)
            if previous is not None:
                return previous
            price = self.limits.quote(price, timestamp)
            row = self.db.execute("SELECT * FROM positions WHERE symbol=?", (symbol,)).fetchone()
            if row is None:
                raise ValueError("No paper position for symbol")
            position = dict(row)
            if datetime.fromisoformat(timestamp) < datetime.fromisoformat(position["last_ts"]):
                raise ValueError("Out-of-order quote rejected")
            self.db.execute("UPDATE positions SET last=?, high=?, last_ts=? WHERE symbol=?", (str(price), str(max(price,money(position["high"]))),timestamp,symbol))
            reason = self.limits.exit_reason(position, price)
            if reason:
                fill = self.limits.fill(price, "SELL")
                proceeds = fill * position["quantity"] - self.limits.fee_per_order
                pnl = (fill-money(position["entry"])) * position["quantity"] - self.limits.fee_per_order
                cash = money(self.status()["cash"]) + proceeds
                self.db.execute("UPDATE account SET cash=? WHERE id=1", (str(cash),))
                self.db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                result = {"symbol":symbol,"side":"SELL","fill":str(fill),"quantity":position["quantity"],"reason":reason,"net_trade_pnl":str(pnl-money(position["entry_fee"])),"mode":"local_paper"}
                self.event("SELL",result,request_id,pnl)
            else:
                result = {"symbol":symbol,"side":"HOLD","price":str(price),"mode":"local_paper"}
                self.event("TICK",result,request_id)
            return result

    def pause(self, paused):
        with self.transaction():
            self.db.execute("UPDATE account SET paused=? WHERE id=1", (int(paused),))
            self.event("PAUSE" if paused else "RESUME", {"paused":paused})
        return {"paused":paused,"note":"Protection checks still run when ticks are supplied"}
