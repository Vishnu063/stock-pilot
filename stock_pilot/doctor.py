"""Read-only installation checks. Never downloads models or exposes secrets."""
import importlib.util
import json
import platform
from urllib.request import urlopen


def diagnose():
    modules = {name: importlib.util.find_spec(name) is not None for name in ('tradingagents', 'yfinance', 'quantstats')}
    model = {'reachable': False, 'models': []}
    try:
        with urlopen('http://127.0.0.1:11434/api/tags', timeout=3) as response:
            data = json.load(response)
        model = {'reachable': True, 'models': [m['name'] for m in data.get('models', []) if isinstance(m, dict) and 'name' in m]}
    except Exception:
        pass
    return {'python': platform.python_version(), 'optional_packages': modules, 'local_ollama': model,
            'market_feed_verified': False, 'live_execution': False,
            'next': ['Install only the optional packages you need',
                     'Start Ollama and choose an installed tool-capable model for research',
                     'Validate an actual market quote and a full research run on your target server']}
