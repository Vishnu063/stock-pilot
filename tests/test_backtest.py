import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from stock_pilot.backtest import evaluate, simulate, load_bars
from tests.test_costs import schedule


class BacktestTests(unittest.TestCase):
    def bars(self, n=130):
        return [
            {
                "date": date(2025, 1, 1) + timedelta(days=i),
                "open": __import__("decimal").Decimal(100 + i),
                "high": __import__("decimal").Decimal(102 + i),
                "low": __import__("decimal").Decimal(99 + i),
                "close": __import__("decimal").Decimal(101 + i),
                "volume": 10000,
            }
            for i in range(n)
        ]

    def write(self, path, bars):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["date", "open", "high", "low", "close", "volume"]
            )
            w.writeheader()
            w.writerows(bars)

    def test_training_selection_ignores_holdout_prices(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bars.csv"
            bars = self.bars()
            self.write(p, bars)
            first = evaluate(p, schedule(), bars[85]["date"].isoformat())
            for b in bars[85:]:
                b.update(open=10, high=11, low=9, close=10)
            self.write(p, bars)
            second = evaluate(p, schedule(), bars[85]["date"].isoformat())
            self.assertEqual(
                first["selected_on_training_only"], second["selected_on_training_only"]
            )
            self.assertEqual(first["training_trials"], second["training_trials"])
            self.assertNotEqual(
                first["holdout"]["net_return"], second["holdout"]["net_return"]
            )

    def test_todays_close_does_not_change_todays_open_signal(self):
        bars = self.bars(60)
        a = simulate(bars, 30, 60, 5, 20, schedule())
        bars[30]["close"] = __import__("decimal").Decimal("1")
        b = simulate(bars, 30, 60, 5, 20, schedule())
        self.assertEqual(a["events"][0], b["events"][0])

    def test_date_order_and_short_samples_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bars.csv"
            bars = self.bars(40)
            self.write(p, bars)
            with self.assertRaises(ValueError):
                evaluate(p, schedule(), "2025-01-20")
            self.write(p, list(reversed(bars)))
            with self.assertRaises(ValueError):
                load_bars(p)
