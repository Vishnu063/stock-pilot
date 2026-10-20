"""Monitor heartbeats and a separate, local-only watchdog. No external messages."""

import json
from contextlib import closing
import sqlite3
import time
import math
from datetime import datetime, timezone
from pathlib import Path
from .journal import initialize, append


def heartbeat(db, state, payload):
    db.execute(
        "CREATE TABLE IF NOT EXISTS monitor_health(name TEXT PRIMARY KEY,updated_at REAL NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL)"
    )
    db.execute(
        """INSERT INTO monitor_health VALUES('paper-monitor',?,?,?)
                  ON CONFLICT(name) DO UPDATE SET updated_at=excluded.updated_at,state=excluded.state,payload=excluded.payload""",
        (time.time(), state, json.dumps(payload)),
    )


def check(path, max_age=90, now=None):
    if type(max_age) is not int or max_age < 1:
        raise ValueError("Heartbeat age limit must be positive whole seconds")
    now = time.time() if now is None else now
    path = Path(path)
    if not path.is_file():
        return {
            "status": "CRITICAL",
            "code": "DATABASE_UNAVAILABLE",
            "message": "Paper account database is unavailable",
        }
    try:
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
        ) as db:
            held = db.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            row = (
                db.execute(
                    "SELECT updated_at,state FROM monitor_health WHERE name='paper-monitor'"
                ).fetchone()
                if "monitor_health" in tables
                else None
            )
        if not held:
            return {
                "status": "IDLE",
                "code": "NO_OPEN_POSITIONS",
                "message": "No open paper positions need monitoring",
            }
        if row is None:
            return {
                "status": "CRITICAL",
                "code": "MONITOR_NOT_STARTED",
                "message": "Open paper positions have no monitor heartbeat",
            }
        age = now - row[0]
        if age < 0 or age > max_age:
            return {
                "status": "CRITICAL",
                "code": "MONITOR_HEARTBEAT_EXPIRED",
                "message": "Paper monitor is stopped, stalled or overdue",
                "age_seconds": round(age),
            }
        if row[1] == "collecting":
            return {
                "status": "BUSY",
                "code": "MONITOR_REFRESHING",
                "message": "Monitor is refreshing quotes; heartbeat is recent",
                "age_seconds": round(age),
            }
        if row[1] != "healthy":
            return {
                "status": "CRITICAL",
                "code": "MONITOR_" + row[1].upper(),
                "message": "Paper monitoring is not healthy; inspect the feed and monitor process",
            }
        return {
            "status": "HEALTHY",
            "code": "MONITOR_ACTIVE",
            "message": "Recent paper-monitor heartbeat",
            "age_seconds": round(age),
        }
    except (sqlite3.Error, OSError, ValueError):
        return {
            "status": "CRITICAL",
            "code": "DATABASE_UNREADABLE",
            "message": "Cannot inspect the paper account",
        }


def pause_entries(path):
    with closing(
        sqlite3.connect(Path(path).resolve().as_uri() + "?mode=rw", uri=True, timeout=3)
    ) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT paused FROM account WHERE id=1").fetchone()
        if row is not None and not row[0]:
            db.execute("UPDATE account SET paused=1 WHERE id=1")
            initialize(db)
            append(db, "WATCHDOG_PAUSE", {"reason": "Monitor health requires review"})
            db.commit()


def supervise(path, alerts, interval=5, cycles=None, max_age=90, emit=print):
    if (
        not math.isfinite(interval)
        or interval < 1
        or (cycles is not None and (type(cycles) is not int or cycles < 1))
    ):
        raise ValueError("Watchdog interval/cycles must be positive")
    alerts = Path(alerts)
    alerts.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    previous = None
    try:
        while cycles is None or count < cycles:
            result = check(path, max_age)
            if result["status"] == "CRITICAL":
                try:
                    pause_entries(path)
                except (sqlite3.Error, OSError):
                    result["pause_failed"] = True
            signature = (result["status"], result["code"])
            if signature != previous:
                record = {"timestamp": datetime.now(timezone.utc).isoformat(), **result}
                with open(alerts, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                emit(json.dumps(record))
                previous = signature
            count += 1
            if cycles is None or count < cycles:
                time.sleep(interval)
    except KeyboardInterrupt:
        return {"status": "STOPPED", "message": "Local watchdog stopped"}
    return {
        "status": "COMPLETED",
        "checks": count,
        "alerts": str(alerts),
        "last_health": result,
    }
