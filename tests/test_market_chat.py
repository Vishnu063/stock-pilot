import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from stock_pilot.market import collect, quote_from_metadata, write_feed, yahoo_quote
from stock_pilot.chat import explain
from stock_pilot.manager import Manager
from stock_pilot.monitor import watch
from stock_pilot.paper import PaperBroker
from stock_pilot.risk import Limits


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.metadata = {'symbol': 'TEST.NS', 'currency': 'INR', 'regularMarketTime': 1792450000,
                         'regularMarketPrice': 100}

    def test_preserves_market_time(self):
        q = quote_from_metadata('TEST.NS', self.metadata)
        self.assertEqual(datetime.fromisoformat(q['timestamp']).timestamp(), 1792450000)
        self.assertNotEqual(q['timestamp'], q['fetched_at'])

    def test_missing_time_currency_and_symbol_rejected(self):
        for field, value in (('regularMarketTime', None), ('currency', 'USD'),
                             ('symbol', 'OTHER.NS'), ('regularMarketPrice', float('nan'))):
            data = dict(self.metadata); data[field] = value
            with self.assertRaises((ValueError, TypeError)):
                quote_from_metadata('TEST.NS', data)

    def test_no_candle_close_fallback(self):
        ticker = MagicMock()
        ticker.get_history_metadata.return_value = self.metadata
        factory = MagicMock(return_value=ticker)
        self.assertEqual(yahoo_quote('TEST.NS', factory)['price'], '100')
        ticker.history.assert_called_once()

    def test_partial_collection_and_atomic_file(self):
        def fetch(symbol):
            if symbol == 'FAIL.NS':
                raise RuntimeError('sensitive vendor body')
            return quote_from_metadata(symbol, self.metadata)
        quotes, errors = collect(['TEST.NS', 'FAIL.NS'], fetch)
        self.assertEqual(list(quotes), ['TEST.NS'])
        self.assertNotIn('sensitive', json.dumps(errors))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'nested'/'quotes.json'
            write_feed(path, quotes)
            self.assertEqual(json.loads(path.read_text()), quotes)
            self.assertEqual(len(list(path.parent.iterdir())), 1)

    def test_feed_write_failure_pauses_entries(self):
        b = PaperBroker(':memory:', Limits('10000','200','500'))
        with patch('stock_pilot.market.collect', return_value=({}, [])), patch('stock_pilot.market.write_feed', side_effect=OSError):
            watch(b, 'unused', interval=30, cycles=1, emit=lambda v: None, source='yahoo')
            self.assertTrue(b.status()['paused'])
        b.db.close()

    def test_automatic_watch_uses_held_symbols(self):
        b = PaperBroker(':memory:', Limits('10000','200','500'))
        now = datetime.now(timezone.utc).isoformat()
        b.buy('TEST.NS', 1, '100', now, '95', 'entry')
        with tempfile.TemporaryDirectory() as d, patch('stock_pilot.market.collect', return_value=({'TEST.NS': {'price':'94','timestamp':now}},[])) as collector:
            watch(b, Path(d)/'feed.json', interval=30, cycles=1, emit=lambda v:None, source='yahoo')
            collector.assert_called_once_with(['TEST.NS'])
            self.assertFalse(b.status()['positions'])
        b.db.close()


class ChatTests(unittest.TestCase):
    def test_model_has_no_execution_path(self):
        b = PaperBroker(':memory:', Limits('10000','200','500'))
        with patch('stock_pilot.chat.explain', return_value={'manager':'I sold everything','execution_allowed':False}):
            manager = Manager(b, model='test')
            before = b.status()
            answer = manager.reply('please do all trading automatically')
            self.assertFalse(answer['execution_allowed'])
            self.assertEqual(before, b.status())
        b.db.close()

    def test_failure_falls_back_to_explicit_commands(self):
        b = PaperBroker(':memory:', Limits('10000','200','500'))
        with patch('stock_pilot.chat.explain', side_effect=TimeoutError):
            m = Manager(b, model='test')
            self.assertEqual(m.reply('explain risk')['error_type'], 'TimeoutError')
            self.assertTrue(m.reply('pause trading')['paused'])
        b.db.close()

    def test_local_chat_payload_and_response(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'message':{'content':'Read-only explanation'}}).encode()
        with patch('stock_pilot.chat.urlopen',return_value=response) as request:
            result = explain('What is my risk?',{},[],model='test')
            self.assertFalse(result['execution_allowed'])
            body = json.loads(request.call_args.args[0].data)
            self.assertNotIn('tools',body)
            self.assertFalse(body['stream'])


if __name__ == '__main__':
    unittest.main()
