import unittest
from decimal import Decimal

from stock_pilot.backtest import simulate
from tests import test_backtest
from tests.test_costs import schedule


class LiquidityTests(unittest.TestCase):
    def run_bars(self, bars, **options):
        return simulate(bars, 30, len(bars), 5, 20, schedule(), **options)

    def bars(self, n=35):
        return test_backtest.BacktestTests().bars(n)

    def test_zero_volume_never_fills(self):
        bars = self.bars()
        for b in bars:
            b["volume"] = 0
        result = self.run_bars(bars)
        self.assertEqual(result["events"], [])
        self.assertTrue(all(o["status"] == "UNFILLED" for o in result["orders"]))
        self.assertEqual(Decimal(result["ending_cash"]), 100000)

    def test_partial_entry_cancels_remainder(self):
        bars = self.bars()
        bars[30]["volume"] = 300
        result = self.run_bars(bars, buy_hold=True)
        entry = result["orders"][0]
        self.assertEqual(entry["status"], "PARTIAL")
        self.assertEqual(entry["filled_quantity"], 3)
        self.assertGreater(entry["unfilled_quantity"], 0)
        self.assertEqual(sum(e["side"] == "BUY" for e in result["events"]), 1)

    def test_entry_and_stop_share_daily_capacity(self):
        bars = self.bars()
        bars[30].update(volume=300, low=Decimal(1))
        result = self.run_bars(bars)
        today = [e for e in result["events"] if e["date"] == str(bars[30]["date"])]
        self.assertEqual(sum(e["quantity"] for e in today), 3)
        stop = [o for o in result["orders"] if o["reason"] == "gap_or_intrabar_stop"][0]
        self.assertEqual(stop["filled_quantity"], 0)
        self.assertTrue(any(e["reason"] == "pending_exit" for e in result["events"]))

    def test_partial_exit_persists_even_after_rebound(self):
        bars = self.bars(34)
        bars[30]["volume"] = 300
        bars[31].update(volume=100, low=Decimal(1))
        bars[32]["volume"] = 100
        bars[33]["volume"] = 100
        result = self.run_bars(bars)
        sells = [e for e in result["events"] if e["side"] == "SELL"]
        self.assertEqual([e["quantity"] for e in sells], [1, 1, 1])
        self.assertEqual(result["closed_trades"], 1)
        self.assertEqual(result["ending_shares"], 0)
        pnl = sum(Decimal(e["net_pnl"]) for e in sells)
        self.assertAlmostEqual(pnl, Decimal(result["ending_cash"]) - 100000)
        self.assertEqual(result["winning_trades"], int(pnl > 0))

    def test_terminal_residual_is_not_fabricated_sale(self):
        bars = self.bars(32)
        bars[30]["volume"] = 300
        bars[31]["volume"] = 0
        result = self.run_bars(bars, buy_hold=True)
        self.assertEqual(result["ending_shares"], 3)
        self.assertEqual(result["closed_trades"], 0)
        expected = Decimal(result["ending_cash"]) + 3 * bars[-1]["close"]
        self.assertEqual(Decimal(result["ending_equity"]), expected)
        self.assertEqual(Decimal(result["net_return"]), (expected - 100000) / 100000)

    def test_every_day_respects_aggregate_capacity(self):
        bars = self.bars(60)
        for b in bars:
            b.update(volume=300, low=Decimal(1))
        result = self.run_bars(bars)
        for bar in bars:
            filled = sum(e["quantity"] for e in result["events"] if e["date"] == str(bar["date"]))
            self.assertLessEqual(filled, 3)
        self.assertGreaterEqual(Decimal(result["ending_cash"]), 0)

    def test_documented_module_command_opens_cli(self):
        import subprocess
        import sys

        result = subprocess.run([sys.executable, "-m", "stock_pilot", "backtest", "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--max-volume-fraction", result.stdout)

    def test_invalid_participation_rejected(self):
        for fraction in ["0", "-1", "1.01", "NaN", "Infinity"]:
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                self.run_bars(self.bars(), max_volume_fraction=fraction)
