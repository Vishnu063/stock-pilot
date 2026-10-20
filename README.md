# Stock Pilot

A guided Manager for stock research and paper trading, with five coordinated roles and fixed risk checks.

**v0.6.1 — paper only. No live broker orders.** Model and market-data quality still need validation on your server. The system does not guarantee profits.

## Start here

Python 3.11 or newer is required:

```bash
git clone https://github.com/Vishnu063/stock-pilot.git
cd stock-pilot
python3 start.py
```

No API key or optional package is needed to open the menu or try the offline demo. If the repository is already cloned, run `git pull` and `python3 start.py` from its folder.

The menu gives you six choices:

1. **Setup check** — see missing packages, Ollama/model status and monitor health.
2. **Offline demo** — watch all five roles produce a decision using synthetic data.
3. **Manager chat** — ask about the portfolio, saved research, pause or resume.
4. **Portfolio** — see paper cash, positions, entry status and marked equity.
5. **Safety and backups** — pause, emergency-block entries, back up or restore a copy.
6. **Advanced workflows** — research a stock, run an agency job, evaluate Qwen or check a quote.

The demo is isolated from your account. Its NO_TRADE result is expected when sources and policies are missing. It is not a demonstration of investment returns.

## Enable local research when ready

First install and start [Ollama](https://ollama.com/download) on your server. Then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[research,market]"
ollama pull qwen3:4b
python start.py
```

Run **Setup check**, then choose **Advanced workflows → Research a stock**. Enter a symbol such as `TCS` or `TCS.NS`; no job JSON is needed for this research action. The app saves the report and shows its opinion. It never places an order. Source claims still need review.

CPU operation on an 8 GB server is the target; actual speed, memory use, model accuracy and usable market-data access remain unverified. Research jobs should run sequentially.

## Paper account and safety

The guided account lives under `data/paper/` and starts paused. Its settings are demonstration values, not your personal capital or loss limits. Private account data is ignored by Git. The guided console never enables live mode, even if broker credentials are present elsewhere. `STOCK_PILOT_MODE=live` is rejected before a profile is opened.

The advanced CLI's older default `paper.db` is separate. To inspect an existing account explicitly:

```bash
python3 start.py --db paper.db
```

An **emergency entry block** persists across restarts. Ordinary resume cannot clear it. A reviewed clear leaves entries paused until you explicitly resume. Existing exit checks are not disabled, but they still require valid quotes and a running monitor.

Backups use SQLite's backup API and verify database/journal integrity. Restores create a **new, paused, entry-locked copy**, never overwrite the running account, and need review before use. Backups include database state only; research files, source snapshots, configuration and model weights need separate preservation.

The separate watchdog detects missing, stalled or unhealthy paper monitoring, pauses new local entries when possible, and writes local console/file alerts. It is not an SMS/email service and cannot report a whole-host outage from that same host. It does not create broker-hosted protection.

## More detail

- [Guided use, recovery and safety commands](docs/GETTING_STARTED.md)
- [Five-role agency, checkpoints, Qwen checks and reconciliation](docs/AGENCY_WORKFLOW.md)
- [Evidence, costs, backtesting and no-trade decisions](docs/RESEARCH_WORKFLOW.md)
- [Full command reference](docs/COMMAND_REFERENCE.md)
- [What has and has not been validated](docs/VALIDATION.md)

## Check historical data

Run `python -m stock_pilot data-check bars.csv` before a backtest. Reports flag missing
metadata, session mismatches, zero volume and large price gaps. See the
[metadata format and limitations](docs/RESEARCH_WORKFLOW.md#historical-data-checks-v061).
These diagnostics do not authenticate data or correct corporate actions.

## Tests

```bash
python -m unittest discover -s tests -v
```

Tests use synthetic data and mocked integrations. Passing them does not establish profitability or live readiness.
