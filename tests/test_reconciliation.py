import copy
import unittest
from datetime import datetime, timedelta, timezone
from stock_pilot.reconciliation import reconcile


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.order = {
            "client_id": "stop-1",
            "broker_order_id": "broker-1",
            "instrument": "NSE:TEST:CNC",
            "side": "SELL",
            "quantity": 10,
            "filled_quantity": 0,
            "status": "OPEN",
            "purpose": "PROTECTION",
            "order_type": "STOP",
            "trigger_price": "95",
        }
        self.expected = {
            "positions": [{"instrument": "NSE:TEST:CNC", "quantity": 10}],
            "orders": [self.order],
        }
        self.observed = copy.deepcopy(self.expected)
        self.observed.update(
            source="synthetic broker export",
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def codes(self):
        return {r["code"] for r in reconcile(self.expected, self.observed)["issues"]}

    def test_matched_snapshot_still_cannot_trade(self):
        result = reconcile(self.expected, self.observed)
        self.assertEqual(result["status"], "MATCHED")
        self.assertFalse(result["execution_allowed"])

    def test_partial_stop_fill_covers_only_remaining_position(self):
        self.observed["positions"][0]["quantity"] = 7
        self.expected["positions"][0]["quantity"] = 7
        self.observed["orders"][0].update(status="PARTIALLY_FILLED", filled_quantity=3)
        self.assertEqual(reconcile(self.expected, self.observed)["status"], "MATCHED")

    def test_missing_partial_and_rejected_protection_detected(self):
        self.observed["orders"][0]["quantity"] = 5
        self.assertIn("UNPROTECTED_REMAINDER", self.codes())
        self.observed["orders"][0]["status"] = "REJECTED"
        self.assertIn("ORDER_NOT_ACTIVE_OR_FILLED", self.codes())

    def test_stale_unknown_and_unconfirmed(self):
        self.observed["captured_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        self.observed["orders"] = []
        self.assertIn("STALE_OR_FUTURE_BROKER_SNAPSHOT", self.codes())
        self.assertIn("UNCONFIRMED_ORDER", self.codes())
        self.observed["orders"] = [{**self.order, "status": "UNKNOWN"}]
        self.assertIn("UNKNOWN_ORDER_STATUS", self.codes())

    def test_open_entry_is_not_treated_as_fully_executed(self):
        pending = {
            **self.order,
            "client_id": "entry",
            "broker_order_id": "buy-1",
            "side": "BUY",
            "purpose": "ENTRY",
            "order_type": "LIMIT",
            "quantity": 20,
            "filled_quantity": 10,
            "status": "PARTIALLY_FILLED",
        }
        self.observed["orders"].append(pending)
        self.expected["orders"].append(pending)
        self.assertIn("ENTRY_ORDER_REMAINS_OPEN", self.codes())

    def test_wrong_account_rejected(self):
        self.expected["account_id"] = "expected-account"
        self.observed["account_id"] = "other-account"
        self.assertIn("ACCOUNT_ID_MISMATCH", self.codes())

    def test_duplicate_and_oversell(self):
        extra = {**self.order, "client_id": "stop-2", "broker_order_id": "broker-2"}
        self.observed["orders"].append(extra)
        self.assertIn("OVERSELL_RISK", self.codes())
        self.observed["orders"].append(copy.deepcopy(self.order))
        self.assertIn("DUPLICATE_CLIENT_ID", self.codes())
