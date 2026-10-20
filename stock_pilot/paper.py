"""Persistent, long-only simulator. Never submits broker orders."""

import json
import sqlite3
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from .risk import money, positive, quantity


def day():
    return datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


class PaperBroker:
    def __init__(
        self, path, limits, starting_cash="100000", cost_schedule=None, instruments=None
    ):
        self.limits = limits
        self.cost_schedule = cost_schedule
        self.instruments = instruments or {}
        self.db = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS account(id INTEGER PRIMARY KEY CHECK(id=1), cash TEXT NOT NULL, paused INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY, quantity INTEGER NOT NULL, entry TEXT NOT NULL, stop TEXT NOT NULL, high TEXT NOT NULL, trailing_pct TEXT, last TEXT NOT NULL, entry_fee TEXT NOT NULL, last_ts TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, request_id TEXT UNIQUE, timestamp TEXT NOT NULL, day TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, pnl TEXT NOT NULL);
        """)
        if "position_id" not in {
            row[1] for row in self.db.execute("PRAGMA table_info(positions)")
        }:
            self.db.execute(
                "ALTER TABLE positions ADD COLUMN position_id TEXT NOT NULL DEFAULT ''"
            )
        for row in self.db.execute(
            "SELECT symbol FROM positions WHERE position_id='' "
        ).fetchall():
            self.db.execute(
                "UPDATE positions SET position_id=? WHERE symbol=?",
                (str(uuid4()), row[0]),
            )
        for name in ("sector", "risk_group"):
            if name not in {
                row[1] for row in self.db.execute("PRAGMA table_info(positions)")
            }:
                self.db.execute(f"ALTER TABLE positions ADD COLUMN {name} TEXT")
        if "peak_equity" not in {
            row[1] for row in self.db.execute("PRAGMA table_info(account)")
        }:
            self.db.execute("ALTER TABLE account ADD COLUMN peak_equity TEXT")
        if "entry_lock" not in {
            row[1] for row in self.db.execute("PRAGMA table_info(account)")
        }:
            self.db.execute("ALTER TABLE account ADD COLUMN entry_lock TEXT")
        from .journal import initialize

        initialize(self.db)
        self.db.execute(
            "INSERT OR IGNORE INTO account(id,cash) VALUES(1,?)",
            (str(positive(starting_cash)),),
        )

        if (
            self.db.execute("SELECT peak_equity FROM account WHERE id=1").fetchone()[0]
            is None
        ):
            current = self.status()
            self.db.execute(
                "UPDATE account SET peak_equity=? WHERE id=1", (current["equity"],)
            )

    def update_peak(self):
        status = self.status()
        if money(status["equity"]) > money(status["peak_equity"]):
            self.db.execute(
                "UPDATE account SET peak_equity=? WHERE id=1", (status["equity"],)
            )

    def portfolio_entry(self, symbol, value, status):
        if (
            self.limits.max_drawdown_pct is not None
            and money(status["drawdown_pct"]) >= self.limits.max_drawdown_pct
        ):
            raise ValueError("Portfolio drawdown limit reached; entry blocked")
        meta = self.instruments.get(symbol, {})
        for field, cap in (
            ("sector", self.limits.max_sector_exposure),
            ("risk_group", self.limits.max_group_exposure),
        ):
            label = meta.get(field)
            if cap is not None:
                if not isinstance(label, str) or not label.strip():
                    raise ValueError(f"Missing {field} classification")
                if any(not p.get(field) for p in status["positions"]):
                    raise ValueError(f"Existing position lacks {field} classification")
                exposure = sum(
                    (
                        money(p["last"]) * p["quantity"]
                        for p in status["positions"]
                        if p[field] == label
                    ),
                    Decimal(0),
                )
                if exposure + value > cap:
                    raise ValueError(f"Maximum {field} exposure exceeded")
        return meta

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
        self.db.execute(
            "INSERT INTO events(request_id,timestamp,day,kind,payload,pnl) VALUES(?,?,?,?,?,?)",
            (
                request_id,
                datetime.now(timezone.utc).isoformat(),
                day(),
                kind,
                json.dumps(payload),
                str(pnl),
            ),
        )
        from .journal import append

        append(
            self.db,
            kind,
            {
                "request_id": request_id,
                "result": payload,
                "realized_pnl_delta": str(pnl),
            },
        )

    def costs(self, price, qty, side):
        if self.cost_schedule is not None:
            return self.cost_schedule.calculate(price, qty, side, day())
        return {
            "schedule": "legacy_flat_fee",
            "reviewed": False,
            "total": str(self.limits.fee_per_order),
            "items": {"flat_fee": str(self.limits.fee_per_order)},
        }

    def duplicate(self, request_id):
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A nonempty unique request ID is required")
        row = self.db.execute(
            "SELECT payload FROM events WHERE request_id=?", (request_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def status(self):
        account = dict(self.db.execute("SELECT * FROM account").fetchone())
        positions = [
            dict(r) for r in self.db.execute("SELECT * FROM positions ORDER BY symbol")
        ]
        realized = sum(
            (
                money(r[0])
                for r in self.db.execute("SELECT pnl FROM events WHERE day=?", (day(),))
            ),
            Decimal(0),
        )
        unrealized = sum(
            ((money(p["last"]) - money(p["entry"])) * p["quantity"] for p in positions),
            Decimal(0),
        )
        equity = money(account["cash"]) + sum(
            (money(p["last"]) * p["quantity"] for p in positions), Decimal(0)
        )
        peak = money(account.get("peak_equity") or equity)
        drawdown = (
            max(Decimal(0), (peak - equity) / peak * 100) if peak > 0 else Decimal(0)
        )
        return {
            "equity": str(equity),
            "peak_equity": str(peak),
            "drawdown_pct": str(drawdown),
            "mode": "local_paper",
            "cash": account["cash"],
            "paused": bool(account["paused"]),
            "entry_lock": account.get("entry_lock"),
            "positions": positions,
            "realized_today": str(realized),
            "open_pnl": str(unrealized),
            "loss_guard_pnl": str(realized + unrealized),
        }

    def buy(
        self,
        symbol,
        qty,
        price,
        timestamp,
        stop,
        request_id,
        trailing_pct=None,
        *,
        preview=False,
    ):
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
            if status.get("entry_lock"):
                raise ValueError("New entries are locked: " + status["entry_lock"])
            if status["paused"]:
                raise ValueError("Manager paused new entries")
            if any(p["symbol"] == symbol for p in status["positions"]):
                raise ValueError("Position already exists; averaging down is disabled")
            if trailing_pct is not None and not (0 < positive(trailing_pct) < 100):
                raise ValueError("Trailing percentage must be between 0 and 100")
            if len(status["positions"]) >= self.limits.max_open_positions:
                raise ValueError("Maximum open positions reached")
            for position in status["positions"]:
                self.limits.quote(position["last"], position["last_ts"])
            exposure = sum(
                (money(p["last"]) * p["quantity"] for p in status["positions"]),
                Decimal(0),
            )
            if exposure + price * qty > self.limits.max_total_exposure:
                raise ValueError("Maximum total exposure exceeded")
            meta = self.portfolio_entry(symbol, price * qty, status)
            cost_details = self.costs(price, qty, "BUY")
            entry_fee = money(cost_details["total"])
            exit_fee = money(
                self.costs(self.limits.fill(positive(stop), "SELL"), qty, "SELL")[
                    "total"
                ]
            )
            self.limits.entry(
                price,
                qty,
                stop,
                money(status["loss_guard_pnl"]),
                money(status["cash"]),
                entry_fee,
                exit_fee,
            )
            cost = price * qty + entry_fee
            if preview:
                return {
                    "symbol": symbol,
                    "quantity": qty,
                    "entry_fill": str(price),
                    "costs": cost_details,
                    "stop_exit_cost": str(exit_fee),
                    "cash_required": str(cost),
                    "execution_allowed": False,
                }
            self.db.execute(
                "UPDATE account SET cash=? WHERE id=1",
                (str(money(status["cash"]) - cost),),
            )
            position_id = str(uuid4())
            self.db.execute(
                "INSERT INTO positions(symbol,quantity,entry,stop,high,trailing_pct,last,entry_fee,last_ts,position_id,sector,risk_group) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol,
                    qty,
                    str(price),
                    str(positive(stop)),
                    str(price),
                    str(trailing_pct) if trailing_pct is not None else None,
                    str(price),
                    str(entry_fee),
                    timestamp,
                    position_id,
                    meta.get("sector"),
                    meta.get("risk_group"),
                ),
            )
            result = {
                "symbol": symbol,
                "position_id": position_id,
                "side": "BUY",
                "quantity": qty,
                "fill": str(price),
                "mode": "local_paper",
                "costs": cost_details,
            }
            self.event("BUY", result, request_id, -entry_fee)
            self.update_peak()
            return result

    def tick(self, symbol, price, timestamp, request_id):
        with self.transaction():
            previous = self.duplicate(request_id)
            if previous is not None:
                return previous
            price = self.limits.quote(price, timestamp)
            row = self.db.execute(
                "SELECT * FROM positions WHERE symbol=?", (symbol,)
            ).fetchone()
            if row is None:
                raise ValueError("No paper position for symbol")
            position = dict(row)
            if datetime.fromisoformat(timestamp) < datetime.fromisoformat(
                position["last_ts"]
            ):
                raise ValueError("Out-of-order quote rejected")
            self.db.execute(
                "UPDATE positions SET last=?, high=?, last_ts=? WHERE symbol=?",
                (
                    str(price),
                    str(max(price, money(position["high"]))),
                    timestamp,
                    symbol,
                ),
            )
            reason = self.limits.exit_reason(position, price)
            if reason:
                fill = self.limits.fill(price, "SELL")
                cost_details = self.costs(fill, position["quantity"], "SELL")
                exit_fee = money(cost_details["total"])
                proceeds = fill * position["quantity"] - exit_fee
                pnl = (fill - money(position["entry"])) * position[
                    "quantity"
                ] - exit_fee
                cash = money(self.status()["cash"]) + proceeds
                self.db.execute("UPDATE account SET cash=? WHERE id=1", (str(cash),))
                self.db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
                result = {
                    "symbol": symbol,
                    "position_id": position["position_id"],
                    "side": "SELL",
                    "fill": str(fill),
                    "quantity": position["quantity"],
                    "reason": reason,
                    "net_trade_pnl": str(pnl - money(position["entry_fee"])),
                    "mode": "local_paper",
                    "costs": cost_details,
                }
                self.event("SELL", result, request_id, pnl)
            else:
                result = {
                    "symbol": symbol,
                    "side": "HOLD",
                    "price": str(price),
                    "mode": "local_paper",
                }
                self.event("TICK", result, request_id)
            self.update_peak()
            return result

    def emergency_block(self, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("A reason is required")
        with self.transaction():
            self.db.execute(
                "UPDATE account SET paused=1,entry_lock=? WHERE id=1", (reason,)
            )
            self.event("EMERGENCY_ENTRY_BLOCK", {"reason": reason})
        return {
            "entries_locked": True,
            "reason": reason,
            "protective_exits_enabled": True,
        }

    def clear_entry_block(self, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("Explain the review before clearing an entry block")
        with self.transaction():
            self.db.execute("UPDATE account SET entry_lock=NULL,paused=1 WHERE id=1")
            self.event("ENTRY_BLOCK_CLEARED", {"review_reason": reason})
        return {
            "entries_locked": False,
            "paused": True,
            "next": "Entries remain paused; resume explicitly after review",
        }

    def pause(self, paused):
        with self.transaction():
            if not paused and self.status().get("entry_lock"):
                raise ValueError(
                    "Emergency entry block is active; review and clear it first"
                )
            current = bool(
                self.db.execute("SELECT paused FROM account WHERE id=1").fetchone()[0]
            )
            if current != paused:
                self.db.execute(
                    "UPDATE account SET paused=? WHERE id=1", (int(paused),)
                )
                self.event("PAUSE" if paused else "RESUME", {"paused": paused})
        return {
            "paused": paused,
            "note": "Protection checks still run when ticks are supplied",
        }
