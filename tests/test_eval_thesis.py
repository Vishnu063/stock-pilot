import json
import unittest
from datetime import datetime, timedelta, timezone
from stock_pilot.model_eval import evaluate, CASES
from stock_pilot.thesis import create, review
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits


class ModelEvalTests(unittest.TestCase):
    def test_expected_answers_pass_without_financial_readiness_claim(self):
        answers = {c["prompt"]: json.dumps(c["expected"]) for c in CASES}
        result = evaluate(answer_fn=lambda m, p: answers[p])
        self.assertEqual(result["passed"], 5)
        self.assertFalse(result["financial_readiness_established"])

    def test_hallucinated_arithmetic_and_sources_fail(self):
        result = evaluate(
            answer_fn=lambda m, p: (
                '{"cash_required":"9999","sources":["https://invented.example"]}'
            )
        )
        self.assertEqual(result["passed"], 0)

    def test_model_unavailable_is_reported(self):
        def fail(*args):
            raise ConnectionError()

        result = evaluate(answer_fn=fail)
        self.assertEqual(result["passed"], 0)
        self.assertTrue(
            all(r["error_type"] == "ConnectionError" for r in result["results"])
        )


class ThesisTests(unittest.TestCase):
    def setUp(self):
        self.b = PaperBroker(":memory:", Limits("10000", "200", "500"))
        self.now = datetime.now(timezone.utc)
        self.definition = {
            "symbol": "TEST",
            "rationale": "Synthetic earnings thesis",
            "holding_days": 30,
            "review_at": (self.now + timedelta(days=7)).isoformat(),
            "invalidation_rules": [
                {"metric": "revenue_growth_pct", "operator": "lt", "threshold": "0"}
            ],
            "events": [
                {"name": "results", "at": (self.now + timedelta(days=2)).isoformat()}
            ],
        }

    def tearDown(self):
        self.b.db.close()

    def test_immutable_creation_and_review(self):
        self.assertTrue(create(self.b, "thesis", self.definition)["created"])
        self.assertFalse(create(self.b, "thesis", self.definition)["created"])
        self.definition["rationale"] = "changed"
        with self.assertRaises(ValueError):
            create(self.b, "thesis", self.definition)
        result = review(
            self.b,
            "thesis",
            {
                "symbol": "TEST",
                "observed_at": self.now.isoformat(),
                "source_reviewed": True,
                "metrics": {"revenue_growth_pct": "-2"},
            },
        )
        self.assertEqual(result["status"], "THESIS_INVALIDATED")
        self.assertEqual(len(result["upcoming_events"]), 1)
        self.assertFalse(self.b.status()["positions"])

    def test_stale_financial_observations_do_not_renew_thesis(self):
        create(self.b, "thesis", self.definition)
        result = review(
            self.b,
            "thesis",
            {
                "symbol": "TEST",
                "observed_at": (self.now - timedelta(days=200)).isoformat(),
                "source_reviewed": True,
                "metrics": {"revenue_growth_pct": "5"},
            },
        )
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")

    def test_missing_and_future_facts(self):
        create(self.b, "thesis", self.definition)
        facts = {
            "symbol": "TEST",
            "observed_at": self.now.isoformat(),
            "source_reviewed": True,
            "metrics": {},
        }
        self.assertEqual(review(self.b, "thesis", facts)["status"], "INSUFFICIENT_DATA")
        facts["observed_at"] = (self.now + timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError):
            review(self.b, "thesis", facts)
