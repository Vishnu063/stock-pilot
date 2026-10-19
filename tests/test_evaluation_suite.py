import tempfile
import unittest
from pathlib import Path
from tests import test_backtest
from tests.test_costs import schedule
from stock_pilot.evaluation_suite import evaluate_suite


class EvaluationSuiteTests(unittest.TestCase):
    def test_disjoint_periods_and_failed_job_are_retained(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fixture = test_backtest.BacktestTests()
            bars = fixture.bars(220)
            fixture.write(root / "bars.csv", bars)
            jobs = [
                {
                    "symbol": "A",
                    "csv": str(root / "bars.csv"),
                    "split_date": bars[a]["date"].isoformat(),
                    "holdout_end": bars[b]["date"].isoformat(),
                }
                for a, b in [(80, 130), (140, 200)]
            ]
            jobs.append(
                {
                    "symbol": "B",
                    "csv": str(root / "absent.csv"),
                    "split_date": bars[80]["date"].isoformat(),
                    "holdout_end": bars[130]["date"].isoformat(),
                }
            )
            result = evaluate_suite(jobs, schedule())
            self.assertEqual(result["completed_jobs"], 2)
            self.assertEqual(result["failed_jobs"], 1)
            self.assertEqual(result["training_trials"], 4)
            self.assertFalse(result["strategy_promoted"])

    def test_overlap_rejected(self):
        jobs = [
            {
                "symbol": "A",
                "csv": "unused",
                "split_date": "2025-04-01",
                "holdout_end": "2025-06-01",
            },
            {
                "symbol": "A",
                "csv": "unused",
                "split_date": "2025-05-01",
                "holdout_end": "2025-07-01",
            },
        ]
        with self.assertRaisesRegex(ValueError, "overlap"):
            evaluate_suite(jobs, schedule())
