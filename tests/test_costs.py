import unittest
from datetime import datetime, timezone
from decimal import Decimal
from stock_pilot.costs import CostSchedule
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits, money


def schedule():
    # Synthetic rates for arithmetic tests, NOT an actual Indian broker tariff.
    return CostSchedule(
        {
            "name": "synthetic",
            "reviewed": False,
            "effective_from": "2020-01-01",
            "effective_until": "2030-01-01",
            "charges": [
                {"name": "brokerage", "rate_bps": "3", "cap": "20", "gst_pct": "18"},
                {"name": "test_tax", "side": "SELL", "rate_bps": "10", "round_to": "1"},
                {"name": "test_stamp", "side": "BUY", "rate_bps": "1.5"},
                {"name": "test_dp", "side": "SELL", "fixed": "5", "gst_pct": "18"},
            ],
        }
    )


class CostsTests(unittest.TestCase):
    def test_cap_sides_and_gst(self):
        s = schedule()
        buy = s.calculate("1000", 100, "BUY", "2026-01-01")
        self.assertEqual(buy["items"]["brokerage"], "20.00")
        self.assertEqual(buy["items"]["brokerage_gst"], "3.60")
        self.assertNotIn("test_tax", buy["items"])
        self.assertEqual(money(buy["total"]), Decimal("38.60"))
        sell = s.calculate("1000", 100, "SELL", "2026-01-01")
        self.assertEqual(money(sell["total"]), Decimal("129.50"))

    def test_validity(self):
        with self.assertRaises(ValueError):
            schedule().calculate("100", 1, "BUY", "2031-01-01")

    def test_ledger_reconciles_itemized_fees(self):
        b = PaperBroker(
            ":memory:", Limits("10000", "200", "500"), cost_schedule=schedule()
        )
        now = datetime.now(timezone.utc).isoformat()
        buy = b.buy("TEST", 10, "100", now, "95", "entry")
        sell = b.tick("TEST", "94", now, "exit")
        self.assertIn("costs", buy)
        self.assertEqual(
            money(b.status()["cash"]) - 100000, money(sell["net_trade_pnl"])
        )
        self.assertEqual(
            money(b.status()["realized_today"]), money(sell["net_trade_pnl"])
        )
        b.db.close()
