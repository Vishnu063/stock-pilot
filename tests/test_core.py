import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

from stock_pilot.agents import investment_review, research
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits, money
from stock_pilot.integrations import openalgo_status


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.limits = Limits('10000','200','500',fee_per_order='2')
        self.b = PaperBroker(':memory:',self.limits)
        self.now = datetime.now(timezone.utc).isoformat()

    def buy(self, request_id='entry', **kw):
        args=dict(symbol='TEST.NS',qty=10,price='100',timestamp=self.now,stop='95',request_id=request_id)
        args.update(kw)
        return self.b.buy(**args)

    def test_gap_stop_and_fees_reconcile(self):
        self.buy()
        result=self.b.tick('TEST.NS','70',self.now,'gap')
        self.assertEqual(result['reason'],'stop_loss')
        self.assertLess(money(result['net_trade_pnl']), -self.limits.max_trade_loss)
        state=self.b.status()
        self.assertEqual(money(state['cash'])-100000,money(state['realized_today']))
        self.assertEqual(state['positions'],[])

    def test_duplicate_buy_and_exit(self):
        first=self.buy()
        self.assertEqual(self.buy(),first)
        sold=self.b.tick('TEST.NS','94',self.now,'exit')
        cash=self.b.status()['cash']
        self.assertEqual(self.b.tick('TEST.NS','94',self.now,'exit'),sold)
        self.assertEqual(cash,self.b.status()['cash'])

    def test_rejection_rolls_back(self):
        for kw in ({'qty':1000},{'qty':0},{'qty':1.5},{'stop':'110'},{'price':'NaN'},{'trailing_pct':'100'}):
            with self.assertRaises(ValueError):
                self.buy(**kw)
            self.assertEqual(self.b.status()['cash'],'100000')
            self.assertFalse(self.b.status()['positions'])

    def test_stale_future_and_naive_quotes(self):
        for timestamp in ((datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat(),
                          (datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),
                          datetime.now().isoformat()):
            with self.assertRaises(ValueError):
                self.buy(timestamp=timestamp)

    def test_pause_does_not_disable_protection(self):
        self.buy()
        self.b.pause(True)
        with self.assertRaises(ValueError):
            self.buy('other',symbol='OTHER.NS')
        self.assertEqual(self.b.tick('TEST.NS','94',self.now,'exit')['side'],'SELL')

    def test_trailing_stop(self):
        self.buy(trailing_pct='3')
        self.assertEqual(self.b.tick('TEST.NS','110',self.now,'up')['side'],'HOLD')
        self.assertEqual(self.b.tick('TEST.NS','106',self.now,'down')['reason'],'trailing_stop')

    def test_daily_limit_blocks_new_entries(self):
        self.buy()
        self.b.tick('TEST.NS','40',self.now,'crash')
        with self.assertRaisesRegex(ValueError,'Daily loss'):
            self.buy('another',symbol='OTHER.NS')

    def test_fees_not_double_counted_in_guard(self):
        self.buy()
        self.assertEqual(money(self.b.status()['loss_guard_pnl']),Decimal('-2'))

    def test_out_of_order(self):
        self.buy()
        earlier=(datetime.fromisoformat(self.now)-timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,'Out-of-order'):
            self.b.tick('TEST.NS','94',earlier,'old')

    def test_restart_preserves_cash_and_pause(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'paper.db')
            b=PaperBroker(path,self.limits)
            b.buy('TEST',10,'100',self.now,'95','a')
            b.pause(True)
            expected=b.status()
            b.db.close()
            b=PaperBroker(path,self.limits)
            self.assertEqual(b.status(),expected)
            b.db.close()

    def test_manager_cannot_turn_rating_into_order(self):
        r=investment_review({'rating':'Buy'},self.b.status(),self.limits)
        self.assertEqual(r['manager_verdict'],'RESEARCH_ONLY')
        self.b.pause(True)
        self.assertEqual(investment_review({'rating':'Buy'},self.b.status(),self.limits)['manager_verdict'],'REVIEW')


class IntegrationTests(unittest.TestCase):
    def test_research_adapter_contract(self):
        state={key:'Report with source https://example.com' for key in (
            'market_report','news_report','fundamentals_report','investment_plan','trader_investment_plan','final_trade_decision')}
        graph=MagicMock()
        graph.TradingAgentsGraph.return_value.propagate.return_value=(state,'Buy')
        config=MagicMock(DEFAULT_CONFIG={})
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json'; path.write_text('{}')
            with patch.dict(sys.modules,{'tradingagents.default_config':config,'tradingagents.graph.trading_graph':graph}):
                report=research('TEST.NS','2026-10-19',path)
                self.assertFalse(report['execution_allowed'])
                self.assertEqual(report['rating'],'Buy')
                state['news_report']=''
                self.assertEqual(research('TEST.NS','2026-10-19',path)['rating'],'REVIEW')

    def test_openalgo_rejects_remote_plain_http(self):
        with patch.dict('os.environ',{'OPENALGO_URL':'http://broker.example','OPENALGO_API_KEY':'secret'}):
            with self.assertRaisesRegex(ValueError,'HTTPS'):
                openalgo_status()

    def test_openalgo_requires_explicit_true(self):
        for payload,success in (({'status':'success','data':{'analyze_mode':True}},True),
                                ({'status':'success','data':{'analyze_mode':'true'}},False),
                                ({'status':'success','data':{'analyze_mode':False}},False)):
            response=MagicMock()
            response.__enter__.return_value.read.return_value=json.dumps(payload).encode()
            opener=MagicMock()
            opener.open.return_value=response
            with patch.dict('os.environ',{'OPENALGO_URL':'http://127.0.0.1:5000','OPENALGO_API_KEY':'secret'}),patch('stock_pilot.integrations.build_opener',return_value=opener):
                if success:
                    self.assertFalse(openalgo_status()['order_submission_implemented'])
                else:
                    with self.assertRaises(ValueError):
                        openalgo_status()


if __name__ == '__main__':
    unittest.main()
