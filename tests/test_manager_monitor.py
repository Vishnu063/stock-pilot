import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stock_pilot.manager import Manager, compare
from stock_pilot.monitor import monitor_cycle, watch
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits


class ManagerMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.b = PaperBroker(":memory:", Limits("10000", "200", "500"))
        self.now = datetime.now(timezone.utc)
        self.ts = self.now.isoformat()

    def tearDown(self):
        self.b.db.close()
        self.tmp.cleanup()

    def feed(self, price, timestamp=None):
        path = self.root / "quotes.json"
        path.write_text(
            json.dumps({"TEST": {"price": price, "timestamp": timestamp or self.ts}})
        )
        return path

    def buy(self, request="entry"):
        return self.b.buy("TEST", 10, "100", self.ts, "95", request)

    def report(self, symbol, rating="Buy", **overrides):
        r = {
            "symbol": symbol,
            "as_of": self.now.date().isoformat(),
            "generated_at": self.ts,
            "rating": rating,
            "reports": {
                k: "Evidence https://www.nseindia.com/fixture"
                for k in (
                    "market_report",
                    "news_report",
                    "fundamentals_report",
                    "final_trade_decision",
                )
            },
        }
        snapshot = self.root / (symbol + ".source")
        snapshot.write_text("Synthetic filing fixture")
        import hashlib

        r["evidence"] = [
            {
                "symbol": symbol,
                "url": "https://www.nseindia.com/fixture",
                "category": category,
                "published_at": (self.now - timedelta(days=1)).isoformat(),
                "captured_at": self.ts,
                "snapshot": str(snapshot),
                "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            }
            for category in ("news", "fundamentals")
        ]
        r.update(overrides)
        path = self.root / (symbol + ".json")
        path.write_text(json.dumps(r))
        return path

    def test_monitor_stop_and_dedup(self):
        self.buy()
        p = self.feed("101")
        first = monitor_cycle(self.b, p)
        count = self.b.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(first["events"], monitor_cycle(self.b, p)["events"])
        self.assertEqual(
            count, self.b.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        )
        result = monitor_cycle(self.b, self.feed("94"))
        self.assertEqual(result["events"][0]["side"], "SELL")
        self.assertFalse(self.b.status()["positions"])

    def test_reentry_has_new_monitor_identity(self):
        self.buy()
        monitor_cycle(self.b, self.feed("94"))
        self.buy("second-entry")
        monitor_cycle(self.b, self.feed("94"))
        self.assertFalse(self.b.status()["positions"])

    def test_stale_feed_pauses_without_fake_exit(self):
        self.buy()
        path = self.feed("90", (self.now - timedelta(minutes=5)).isoformat())
        result = monitor_cycle(self.b, path)
        self.assertTrue(result["errors"])
        self.assertTrue(self.b.status()["paused"])
        self.assertEqual(len(self.b.status()["positions"]), 1)

    def test_invalid_and_missing_feed(self):
        self.assertTrue(monitor_cycle(self.b, self.root / "absent")["entries_paused"])
        self.buy_after_resume()
        p = self.root / "bad"
        p.write_text("{}")
        self.assertTrue(monitor_cycle(self.b, p)["errors"])
        self.assertTrue(self.b.status()["paused"])

    def buy_after_resume(self):
        self.b.pause(False)
        self.buy()

    def test_watch_cycles(self):
        with patch("stock_pilot.monitor.time.sleep") as sleep:
            result = watch(self.b, self.feed("100"), cycles=2, emit=lambda x: None)
            self.assertEqual(result["cycles"], 2)
            sleep.assert_called_once_with(5)

    def test_manager_only_explicit_actions(self):
        manager = Manager(self.b, self.root)
        self.assertIn("portfolio", manager.reply("Review my portfolio!"))
        self.assertFalse(manager.reply("Buy every stock now")["execution_allowed"])
        self.assertTrue(manager.reply("pause trading")["paused"])
        self.assertFalse(manager.reply("resume trading")["paused"])
        self.assertIn("agents", manager.reply("show agents"))

    def test_manager_why_retains_source_report(self):
        self.report("TEST")
        result = Manager(self.b, self.root).reply("why TEST")
        self.assertEqual(result["report"]["symbol"], "TEST")

    def test_comparison_orders_opinions_not_profit_predictions(self):
        a = self.report("A", "Hold")
        b = self.report("B", "Buy")
        result = compare([a, b], self.now.date().isoformat(), self.b)
        self.assertEqual([r["symbol"] for r in result["candidates"]], ["B", "A"])
        self.assertFalse(result["execution_allowed"])

    def test_missing_sources_dates_and_duplicates_rejected(self):
        good = self.report("GOOD")
        bad = self.report("BAD", reports={})
        old = self.report(
            "OLD", generated_at=(self.now - timedelta(days=2)).isoformat()
        )
        result = compare([good, bad, old, good], self.now.date().isoformat(), self.b)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(len(result["needs_review"]), 3)

    def test_pause_blocks_recommendation_shortlist(self):
        self.b.pause(True)
        result = compare([self.report("GOOD")], self.now.date().isoformat(), self.b)
        self.assertFalse(result["candidates"])

    def test_portfolio_exposure_limit(self):
        self.b.limits = Limits("10000", "200", "500", max_total_exposure="1500")
        self.buy()
        with self.assertRaisesRegex(ValueError, "total exposure"):
            self.b.buy("SECOND", 10, "100", self.ts, "95", "second")

    def test_stale_holding_blocks_new_entry(self):
        self.buy()
        old = (self.now - timedelta(minutes=5)).isoformat()
        self.b.db.execute("UPDATE positions SET last_ts=?", (old,))
        with self.assertRaisesRegex(ValueError, "stale"):
            self.b.buy("SECOND", 1, "100", self.ts, "95", "second")

    def test_malformed_reports_are_rejected(self):
        bad = self.report("BAD", reports=12)
        result = compare([bad], self.now.date().isoformat(), self.b)
        self.assertFalse(result["candidates"])
        self.assertEqual(len(result["needs_review"]), 1)

    def test_max_positions(self):
        self.b.limits = Limits("10000", "200", "500", max_open_positions=1)
        self.buy()
        with self.assertRaisesRegex(ValueError, "open positions"):
            self.b.buy("SECOND", 10, "100", self.ts, "95", "second")


if __name__ == "__main__":
    unittest.main()
