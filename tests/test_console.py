import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from stock_pilot.console import open_profile, run_menu, setup_text
from stock_pilot.health import supervise


class ConsoleTests(unittest.TestCase):
    def test_guided_demo_never_changes_paper_account(self):
        with tempfile.TemporaryDirectory() as d:
            b, root, path, config = open_profile(d)
            before = b.status()
            messages = []
            answers = iter(["2", "4", "0"])
            try:
                self.assertEqual(
                    run_menu(
                        b,
                        root,
                        path,
                        config,
                        ask=lambda p: next(answers),
                        say=messages.append,
                    ),
                    0,
                )
                self.assertEqual(before, b.status())
                self.assertTrue(b.status()["paused"])
                self.assertTrue(any("NO_TRADE" in text for text in messages))
            finally:
                b.db.close()

    def test_live_environment_is_rejected_before_writing_profile(self):
        with (
            tempfile.TemporaryDirectory() as d,
            patch.dict(os.environ, {"STOCK_PILOT_MODE": "live"}),
        ):
            with self.assertRaises(ValueError):
                open_profile(d)
            self.assertFalse((Path(d) / "paper").exists())

    def test_invalid_settings_do_not_open_a_live_profile(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "paper"
            root.mkdir()
            (root / "settings.json").write_text(json.dumps({"mode": "live"}))
            with self.assertRaises(ValueError):
                open_profile(d)
            self.assertFalse((root / "paper.db").exists())

    def test_setup_messages_are_actionable_and_never_claim_ready_to_trade(self):
        result = {
            "python": "3.12",
            "optional_packages": {
                "tradingagents": False,
                "yfinance": False,
                "quantstats": False,
            },
            "local_ollama": {"reachable": False, "models": []},
        }
        text = setup_text(result)
        self.assertIn("ollama pull qwen3:4b", text)
        self.assertIn("Live trading: unavailable", text)

    def test_watchdog_deduplicates_repeated_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "absent.db"
            alerts = Path(d) / "alerts.jsonl"
            with patch("stock_pilot.health.time.sleep"):
                supervise(path, alerts, cycles=2, emit=lambda x: None)
            self.assertEqual(len(alerts.read_text().splitlines()), 1)
            self.assertFalse(path.exists())
