import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stock_pilot.backtest import evaluate, load_bars
from stock_pilot.data_quality import inspect_dataset
from tests import test_backtest
from tests.test_costs import schedule


class DataQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "bars.csv"
        helper = test_backtest.BacktestTests()
        helper.write(self.path, helper.bars())
        self.bars, self.digest = load_bars(self.path)
        self.metadata = {
            "schema_version": 1,
            "dataset_sha256": self.digest,
            "symbol": "TEST.NS",
            "currency": "INR",
            "source_url": "https://example.com/operator-supplied-data",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "price_basis": "raw",
            "corporate_actions": [],
            "corporate_actions_reviewed": True,
            "expected_sessions": [b["date"].isoformat() for b in self.bars],
        }

    def check(self):
        Path(str(self.path) + ".metadata.json").write_text(json.dumps(self.metadata))
        return inspect_dataset(self.path, self.bars, self.digest)

    def test_cli_needs_review_without_creating_account(self):
        import contextlib
        import io
        from stock_pilot.cli import main

        db = Path(self.temp.name) / "must-not-exist.db"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--db", str(db), "data-check", str(self.path)]), 1)
        self.assertFalse(db.exists())

    def test_missing_metadata_visible_in_backtest(self):
        result = evaluate(self.path, schedule(), self.bars[85]["date"].isoformat())
        self.assertEqual(result["data_quality"]["status"], "NEEDS_REVIEW")
        self.assertFalse(result["execution_allowed"])

    def test_declarations_pass_but_never_authorize_execution(self):
        result = self.check()
        self.assertEqual(result["status"], "DECLARED_CHECKS_PASSED")
        self.assertFalse(result["execution_allowed"])

    def test_tampering_rejected(self):
        self.metadata["dataset_sha256"] = hashlib.sha256(b"different").hexdigest()
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.check()

    def test_missing_and_unexpected_sessions(self):
        self.metadata["expected_sessions"] = self.metadata["expected_sessions"][1:] + ["2025-12-31"]
        codes = {i["code"] for i in self.check()["issues"]}
        self.assertEqual(codes, {"MISSING_SESSIONS", "UNEXPECTED_SESSIONS"})

    def test_unsupported_adjustments_and_actions(self):
        for field, value in [("price_basis", "adjusted"), ("corporate_actions", [{"type": "split"}])]:
            with self.subTest(field=field):
                old = self.metadata[field]
                self.metadata[field] = value
                self.assertEqual(self.check()["status"], "NEEDS_REVIEW")
                self.metadata[field] = old

    def test_bad_timestamps_and_duplicate_sessions(self):
        for value in ["2026-01-01T00:00:00", "2999-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"]:
            self.metadata["captured_at"] = value
            with self.assertRaises(ValueError):
                self.check()
        self.metadata["captured_at"] = datetime.now(timezone.utc).isoformat()
        self.metadata["expected_sessions"].append(self.metadata["expected_sessions"][-1])
        with self.assertRaises(ValueError):
            self.check()

    def test_price_jump_and_zero_volume_require_review(self):
        self.bars[1]["open"] *= 2
        self.bars[2]["volume"] = 0
        codes = {i["code"] for i in self.check()["issues"]}
        self.assertIn("LARGE_OVERNIGHT_MOVE", codes)
        self.assertIn("ZERO_VOLUME", codes)
