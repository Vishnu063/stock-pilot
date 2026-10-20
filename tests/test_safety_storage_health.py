import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits
from stock_pilot.storage import backup, restore
from stock_pilot.health import check, heartbeat, supervise


class SafetyStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "paper.db"
        self.limits = Limits("10000", "200", "500")
        self.b = PaperBroker(self.path, self.limits)
        self.ts = datetime.now(timezone.utc).isoformat()

    def tearDown(self):
        self.b.db.close()
        self.temp.cleanup()

    def test_emergency_cannot_be_resumed_but_exit_still_runs(self):
        self.b.buy("TEST", 1, "100", self.ts, "95", "entry")
        self.b.emergency_block("Manual review")
        with self.assertRaises(ValueError):
            self.b.pause(False)
        self.assertEqual(self.b.tick("TEST", "94", self.ts, "exit")["side"], "SELL")
        self.b.clear_entry_block("Checked portfolio and monitor")
        self.assertTrue(self.b.status()["paused"])
        self.b.pause(False)
        self.assertFalse(self.b.status()["paused"])

    def test_backup_restore_preserves_positions_and_locks_new_copy(self):
        self.b.buy("TEST", 1, "100", self.ts, "95", "entry")
        snapshot = self.root / "backup.db"
        backup(self.b, snapshot)
        restored = self.root / "restored.db"
        restore(snapshot, restored)
        recovered = PaperBroker(restored, self.limits)
        try:
            self.assertEqual(recovered.status()["cash"], self.b.status()["cash"])
            self.assertEqual(
                recovered.status()["positions"], self.b.status()["positions"]
            )
            self.assertTrue(recovered.status()["entry_lock"])
            self.assertFalse(self.b.status()["paused"])
            with self.assertRaises(FileExistsError):
                restore(snapshot, restored)
        finally:
            recovered.db.close()

    def test_wal_backup_includes_committed_positions(self):
        self.b.db.execute("PRAGMA journal_mode=WAL")
        self.b.buy("TEST", 1, "100", self.ts, "95", "entry")
        expected = self.b.status()
        snapshot = self.root / "wal-backup.db"
        backup(self.b, snapshot)
        self.b.tick("TEST", "94", self.ts, "later-exit")
        output = self.root / "wal-restored.db"
        restore(snapshot, output)
        recovered = PaperBroker(output, self.limits)
        try:
            self.assertEqual(recovered.status()["positions"], expected["positions"])
            self.assertEqual(recovered.status()["cash"], expected["cash"])
        finally:
            recovered.db.close()

    def test_corrupt_backup_is_rejected(self):
        snapshot = self.root / "backup.db"
        backup(self.b, snapshot)
        with open(snapshot, "ab") as f:
            f.write(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            restore(snapshot, self.root / "new.db")
        self.assertFalse((self.root / "new.db").exists())

    def test_missing_heartbeat_pauses_once_and_alerts_are_deduplicated(self):
        self.b.buy("TEST", 1, "100", self.ts, "95", "entry")
        self.assertEqual(check(self.path)["code"], "MONITOR_NOT_STARTED")
        result = supervise(
            self.path, self.root / "alerts.jsonl", cycles=1, emit=lambda x: None
        )
        self.assertEqual(result["checks"], 1)
        self.assertTrue(self.b.status()["paused"])
        heartbeat(self.b.db, "healthy", {})
        self.assertEqual(check(self.path)["status"], "HEALTHY")
        self.assertEqual(check(self.path, now=10**20)["status"], "CRITICAL")

    def test_recent_collection_is_busy_not_a_false_outage(self):
        self.b.buy("TEST", 1, "100", self.ts, "95", "entry")
        heartbeat(self.b.db, "collecting", {})
        self.assertEqual(check(self.path)["status"], "BUSY")
        supervise(self.path, self.root / "alerts.jsonl", cycles=1, emit=lambda x: None)
        self.assertFalse(self.b.status()["paused"])

    def test_missing_database_is_not_created_by_watchdog(self):
        path = self.root / "absent.db"
        supervise(path, self.root / "alerts.jsonl", cycles=1, emit=lambda x: None)
        self.assertFalse(path.exists())
