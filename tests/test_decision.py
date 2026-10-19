import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from stock_pilot.decision import assess
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits
from tests.test_costs import schedule


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        now = datetime.now(timezone.utc)
        self.ts = now.isoformat()
        from zoneinfo import ZoneInfo

        today = now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
        snapshot = root / "snapshot"
        snapshot.write_text("Synthetic test filing")
        records = [
            {
                "symbol": "TEST",
                "url": "https://www.nseindia.com/test",
                "category": c,
                "published_at": (now - timedelta(days=1)).isoformat(),
                "captured_at": self.ts,
                "snapshot": str(snapshot),
                "sha256": sha256(snapshot.read_bytes()).hexdigest(),
            }
            for c in ("news", "fundamentals")
        ]
        self.report = {
            "symbol": "TEST",
            "as_of": today,
            "generated_at": self.ts,
            "rating": "Buy",
            "evidence": records,
            "reports": {
                k: "https://www.nseindia.com/test"
                for k in (
                    "market_report",
                    "news_report",
                    "fundamentals_report",
                    "final_trade_decision",
                )
            },
        }
        costs = schedule()
        costs.reviewed = True
        self.b = PaperBroker(
            ":memory:",
            Limits(
                "10000",
                "200",
                "500",
                max_drawdown_pct="10",
                max_sector_exposure="10000",
                max_group_exposure="10000",
                min_daily_turnover="1000000",
                max_spread_bps="20",
                min_reward_risk="2",
            ),
            cost_schedule=costs,
            instruments={"TEST": {"sector": "Tech", "risk_group": "Export"}},
        )
        self.proposal = {
            "symbol": "TEST",
            "quantity": 10,
            "stop": "95",
            "target": "120",
            "holding_days": 30,
            "quote": {
                "price": "100",
                "timestamp": self.ts,
                "currency": "INR",
                "source": "synthetic",
            },
            "average_daily_turnover": "10000000",
            "minimum_daily_turnover": "1000000",
            "spread_bps": "5",
            "maximum_spread_bps": "20",
            "minimum_reward_risk": "2",
        }

    def tearDown(self):
        self.b.db.close()
        self.tmp.cleanup()

    def test_paper_candidate_does_not_execute(self):
        before = self.b.status()
        decision = assess(self.report, self.proposal, self.b)
        self.assertEqual(decision["decision"], "PAPER_CANDIDATE")
        self.assertEqual(before, self.b.status())
        self.assertFalse(decision["execution_allowed"])

    def test_unreviewed_costs_and_missing_evidence_reject(self):
        self.b.cost_schedule.reviewed = False
        self.report["evidence"] = []
        result = assess(self.report, self.proposal, self.b)
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertGreaterEqual(len(result["reasons"]), 2)

    def test_bad_reward_and_illiquidity(self):
        self.proposal.update(target="100.1", average_daily_turnover="1")
        self.assertEqual(
            assess(self.report, self.proposal, self.b)["decision"], "NO_TRADE"
        )

    def test_proposal_cannot_lower_policy_threshold(self):
        self.proposal.update(target="106", minimum_reward_risk="0.01")
        result = assess(self.report, self.proposal, self.b)
        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertTrue(any("reward-to-risk" in r for r in result["reasons"]))

    def test_paused_preview_rejects(self):
        self.b.pause(True)
        self.assertEqual(
            assess(self.report, self.proposal, self.b)["decision"], "NO_TRADE"
        )
