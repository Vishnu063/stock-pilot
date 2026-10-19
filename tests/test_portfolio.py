import unittest
from datetime import datetime, timezone
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits


class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.ts = datetime.now(timezone.utc).isoformat()
        self.mapping = {
            "A": {"sector": "Tech", "risk_group": "Export"},
            "B": {"sector": "Tech", "risk_group": "Export"},
            "C": {"sector": "Bank", "risk_group": "Domestic"},
        }

    def broker(self, **kw):
        return PaperBroker(
            ":memory:", Limits("10000", "200", "500", **kw), instruments=self.mapping
        )

    def test_sector_and_group_caps(self):
        for setting in ("max_sector_exposure", "max_group_exposure"):
            b = self.broker(**{setting: "1500"})
            b.buy("A", 10, "100", self.ts, "95", "a")
            with self.assertRaisesRegex(ValueError, "exposure"):
                b.buy("B", 10, "100", self.ts, "95", "b")
            b.buy("C", 1, "100", self.ts, "95", "c")
            b.db.close()

    def test_missing_classification_blocks_entries(self):
        b = self.broker(max_sector_exposure="5000")
        with self.assertRaisesRegex(ValueError, "classification"):
            b.buy("UNKNOWN", 1, "100", self.ts, "95", "entry")
        b.db.close()

    def test_persistent_peak_drawdown_blocks_entry(self):
        b = self.broker(max_drawdown_pct="0.05")
        b.buy("A", 10, "100", self.ts, "95", "entry")
        b.tick("A", "90", self.ts, "loss")
        self.assertGreater(float(b.status()["drawdown_pct"]), 0.05)
        with self.assertRaisesRegex(ValueError, "drawdown"):
            b.buy("B", 1, "100", self.ts, "95", "next")
        b.pause(False)
        with self.assertRaisesRegex(ValueError, "drawdown"):
            b.buy("B", 1, "100", self.ts, "95", "next")
        b.db.close()
