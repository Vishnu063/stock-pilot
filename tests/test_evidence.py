import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from stock_pilot.evidence import attach, check, primary_host


class EvidenceTests(unittest.TestCase):
    def test_primary_domain_spoof_rejected(self):
        self.assertFalse(primary_host("https://nseindia.com.attacker.example/doc"))
        self.assertTrue(primary_host("https://archives.nseindia.com/doc"))
        with self.assertRaises(ValueError):
            primary_host("http://nseindia.com/doc")

    def test_attach_integrity_and_future_gate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            now = datetime.now(timezone.utc)
            report = {
                "symbol": "TEST.NS",
                "as_of": now.date().isoformat(),
                "reports": {
                    "news_report": "https://www.nseindia.com/example",
                    "fundamentals_report": "https://www.nseindia.com/example",
                },
            }
            (root / "report.json").write_text(json.dumps(report))
            (root / "source.txt").write_text(
                "Synthetic source; not real financial evidence"
            )
            manifest = [
                {
                    "symbol": "TEST.NS",
                    "url": "https://www.nseindia.com/example",
                    "category": c,
                    "file": "source.txt",
                    "published_at": (now - timedelta(days=1)).isoformat(),
                    "captured_at": now.isoformat(),
                }
                for c in ("news", "fundamentals")
            ]
            (root / "manifest.json").write_text(json.dumps(manifest))
            attach(root / "report.json", root / "manifest.json", root / "out.json")
            result = json.loads((root / "out.json").read_text())
            self.assertEqual(check(result, report["as_of"]), [])
            Path(result["evidence"][0]["snapshot"]).write_text("changed")
            self.assertTrue(check(result, report["as_of"]))
            manifest[0]["published_at"] = (now + timedelta(days=1)).isoformat()
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                attach(root / "report.json", root / "manifest.json", root / "out.json")

    def test_missing_evidence_fails_closed(self):
        self.assertTrue(check({"symbol": "TEST"}, "2026-10-19"))
