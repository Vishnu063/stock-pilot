import copy
import tempfile
import unittest
from pathlib import Path
from stock_pilot.agency import run
from stock_pilot.journal import entries
from tests import test_decision


class AgencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_decision.DecisionTests()
        self.fixture.setUp()
        self.b = self.fixture.b
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config.json").write_text("{}")
        self.job = {
            "research_config": str(self.root / "config.json"),
            "symbol": "TEST",
            "as_of": self.fixture.report["as_of"],
            "proposal": self.fixture.proposal,
        }
        self.calls = 0

    def tearDown(self):
        self.fixture.tearDown()
        self.tmp.cleanup()

    def research(self, *args):
        self.calls += 1
        return copy.deepcopy(self.fixture.report)

    def test_crash_resume_and_final_journal_exactly_once(self):
        def crash(step):
            if step == "research":
                raise RuntimeError("simulated crash after durable step")

        first = run(
            self.b,
            self.job,
            "run",
            self.root,
            researcher=self.research,
            after_step=crash,
        )
        self.assertEqual(first["status"], "failed")
        second = run(self.b, self.job, "run", self.root, researcher=self.research)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(self.calls, 1)
        run(self.b, self.job, "run", self.root, researcher=self.research)
        self.assertEqual(
            sum(r["kind"] == "AGENCY_DECISION" for r in entries(self.b.db)), 1
        )
        self.assertFalse(self.b.status()["positions"])

    def test_crash_after_manager_commit_does_not_duplicate_journal(self):
        def crash(step):
            if step == "manager":
                raise RuntimeError("simulated failure after commit")

        first = run(
            self.b,
            self.job,
            "run",
            self.root,
            researcher=self.research,
            after_step=crash,
        )
        self.assertEqual(first["status"], "failed")
        second = run(self.b, self.job, "run", self.root, researcher=self.research)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(
            sum(r["kind"] == "AGENCY_DECISION" for r in entries(self.b.db)), 1
        )

    def test_policy_change_requires_new_run_id(self):
        run(self.b, self.job, "run", self.root, researcher=self.research)
        self.job["proposal"]["target"] = "130"
        with self.assertRaisesRegex(ValueError, "changed"):
            run(self.b, self.job, "run", self.root, researcher=self.research)

    def test_cached_candidate_is_revalidated_when_paused(self):
        first = run(self.b, self.job, "run", self.root, researcher=self.research)
        self.assertEqual(first["current_readiness"]["decision"], "PAPER_CANDIDATE")
        self.b.pause(True)
        second = run(self.b, self.job, "run", self.root, researcher=self.research)
        self.assertEqual(second["current_readiness"]["decision"], "NO_TRADE")
        self.assertEqual(second["manager"]["decision"], "NO_TRADE")
        self.assertEqual(self.calls, 1)

    def test_live_quote_failure_never_uses_old_supplied_quote(self):
        from unittest.mock import patch
        self.job['quote_source']='yahoo'
        with patch('stock_pilot.market.yahoo_quote',side_effect=ConnectionError):
            result=run(self.b,self.job,'run',self.root,researcher=self.research)
        self.assertEqual(result['manager']['decision'],'NO_TRADE')
        self.assertEqual(result['current_readiness']['quote_used'],{})

    def test_active_lease_blocks_second_worker(self):
        run(self.b, self.job, "run", self.root, researcher=self.research)
        import time

        self.b.db.execute(
            "UPDATE agency_runs SET status='running',lease_until=?",
            (time.time() + 1000,),
        )
        with self.assertRaisesRegex(ValueError, "active lease"):
            run(self.b, self.job, "run", self.root, researcher=self.research)
