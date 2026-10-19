import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits
from stock_pilot.journal import verify


class UpgradeTests(unittest.TestCase):
    def test_existing_v03_position_survives_migration(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            db = sqlite3.connect(path)
            db.executescript("""
            CREATE TABLE account(id INTEGER PRIMARY KEY,cash TEXT NOT NULL,paused INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE positions(symbol TEXT PRIMARY KEY,quantity INTEGER NOT NULL,entry TEXT NOT NULL,stop TEXT NOT NULL,high TEXT NOT NULL,trailing_pct TEXT,last TEXT NOT NULL,entry_fee TEXT NOT NULL,last_ts TEXT NOT NULL,position_id TEXT NOT NULL);
            INSERT INTO account VALUES(1,'99000',1);
            """)
            db.execute(
                "INSERT INTO positions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    "TEST",
                    10,
                    "100",
                    "95",
                    "100",
                    None,
                    "100",
                    "0",
                    datetime.now(timezone.utc).isoformat(),
                    "existing-position",
                ),
            )
            db.commit()
            db.close()
            b = PaperBroker(path, Limits("10000", "200", "500"))
            self.assertEqual(
                b.status()["positions"][0]["position_id"], "existing-position"
            )
            self.assertEqual(b.status()["cash"], "99000")
            self.assertTrue(b.status()["paused"])
            self.assertEqual(b.status()["peak_equity"], "100000")
            self.assertTrue(verify(b.db)["valid"])
            b.db.close()
