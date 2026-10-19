import unittest
from datetime import datetime, timezone
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits
from stock_pilot.journal import entries, verify, record_assessment, observe


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.b = PaperBroker(":memory:", Limits("10000", "200", "500"))
        self.ts = datetime.now(timezone.utc).isoformat()

    def tearDown(self):
        self.b.db.close()

    def test_orders_and_hash_chain(self):
        self.b.buy("TEST", 10, "100", self.ts, "95", "entry")
        self.b.tick("TEST", "94", self.ts, "exit")
        self.assertEqual(verify(self.b.db)["entries"], 2)
        events = entries(self.b.db)
        self.assertEqual(
            events[0]["payload"]["result"]["position_id"],
            events[1]["payload"]["result"]["position_id"],
        )
        self.b.db.execute("UPDATE journal SET payload='{}' WHERE sequence=1")
        self.assertFalse(verify(self.b.db)["valid"])

    def test_counterfactual_outcomes_are_not_realized_profit(self):
        proposal = {"quote": {"price": "100", "timestamp": self.ts}, "holding_days": 30}
        entry = record_assessment(self.b, {}, proposal, {"decision": "NO_TRADE"})
        now = datetime.now(timezone.utc).isoformat()
        result = observe(self.b, entry, "110", now, "Review after event")
        self.assertEqual(result["classification"], "counterfactual")
        self.assertFalse(result["realized_pnl_claim"])
        with self.assertRaises(ValueError):
            observe(self.b, entry, "110", now, "duplicate")
        self.assertTrue(verify(self.b.db)["valid"])

    def test_failed_order_leaves_no_journal_event(self):
        with self.assertRaises(ValueError):
            self.b.buy("TEST", 0, "100", self.ts, "95", "bad")
        self.assertEqual(entries(self.b.db), [])
