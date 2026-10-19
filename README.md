# Stock Pilot

Five roles working toward evidence-based stock research and controlled automation.
**v0.5 is a research and local paper-trading system. It cannot place live orders.**
Profit is an objective, never a promise. Stops can lose more than their planned amount during price gaps.

## Start in one command

Python 3.11 or newer is required. No API key, GPU, or third-party package is needed for the offline demo.

```bash
git clone https://github.com/Vishnu063/stock-pilot.git
cd stock-pilot
python3 -m stock_pilot.cli demo
```

The synthetic demo buys DEMO, raises its price, and triggers a trailing-stop exit. It is not a backtest or evidence of profitability.

For a short command after installation:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
stock-pilot team
stock-pilot status
```

On Windows, activate with `.venv\Scripts\Activate.ps1` in PowerShell.
Commands below also work as `python -m stock_pilot.cli ...` without installing the base package.

## Run the agency offline

```bash
python -m stock_pilot.cli agency-demo
```

This shows all five role outputs using synthetic inputs. It correctly concludes `NO_TRADE` without verified evidence and configured policy. See [the agency workflow](docs/AGENCY_WORKFLOW.md) for checkpointed research jobs, Qwen evaluation, thesis reviews, multi-stock evaluation and read-only broker reconciliation.

## Your five roles

| Role | Implemented behavior |
|---|---|
| 1. Strategy | Reuses TradingAgents market analysis and trader proposal |
| 2. Capital protection | Fixed entry limits, stop-loss and trailing-stop checks in the local paper ledger |
| 3. Research | Reuses TradingAgents news and fundamentals analysts |
| 4. Manager | Conversational command router for portfolio, saved research, pause and resume |
| 5. Investment analyst | Compares saved analyst ratings, dates and citation presence alongside protection objections |

These are five application roles, not five newly trained models. Research roles share one upstream graph run. The protection role uses deterministic code. The Manager supports explicit conversational actions plus optional read-only local-model explanations. Model text never executes actions.

## Research with a local model

The research integration uses [TradingAgents](https://github.com/TauricResearch/TradingAgents) pinned at `e8f5503e9b86d5c2710b0c76b1f686703968c9df`. It is a dependency, not copied or claimed as our own code.

Install [Ollama](https://ollama.com/) separately, start it, and download a tool-capable model:

```bash
ollama pull qwen3:4b
python -m pip install -e '.[research]'
stock-pilot research RELIANCE.NS --date 2026-10-19
```

Replace the date with your intended analysis date (YYYY-MM-DD, not in the future). `.NS` and `.BO` are Yahoo-style NSE/BSE research symbols; broker symbols may differ.

`examples/research.ollama.json` selects a local endpoint and India-oriented news queries. Adjust model names to your machine. Local AI has RAM and compute costs and may be slow; model quality and Indian-market coverage need validation. Upstream has substantial dependencies. Base demo installation does not install them.

The output is saved to `reports/research.json` with analysis date, generation time, original reports, research rating, missing-report flags, and local risk objections. Citations remain inside upstream reports. **Citation completeness, factual correctness, news coverage and price freshness are not independently verified by this version.** An empty report forces REVIEW; a nonempty report is not proof of adequate evidence. No recommendation automatically buys a stock. The separate comparison command ranks analyst opinions; it does not forecast returns.

## Local paper protection

Review `examples/limits.json` before testing. Its values are demo settings, not recommended personal risk limits. Monetary values share one account currency (default intent: INR); the simulator does not perform currency conversion.

| Setting | Demo value |
|---|---:|
| Starting paper cash | 100000 |
| Maximum value per position | 10000 |
| Planned maximum loss per trade | 200 |
| Daily loss threshold for blocking entries | 500 |
| Quote age limit | 60 seconds |
| Assumed slippage | 10 basis points per fill |
| Assumed fee | 2 per order |

The default flat fee is a placeholder. An optional effective-dated itemized schedule models turnover charges, caps, fixed amounts and taxes on charges. Actual broker tariffs still need verification; see the research workflow below. Daily entry checks use today's realized P&L plus current marked open P&L. Positions are marked only when you supply a quote. Daily buckets use Asia/Kolkata. This is not a start-of-day equity drawdown model. Entries are long-only, one position per symbol, without averaging down or leverage.

Supply a fresh, timezone-aware quote timestamp. In Bash:

```bash
QUOTE_TIME=$(python -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())')
stock-pilot paper-buy RELIANCE.NS --quantity 1 --price 100 --stop 95 --trailing-pct 3 --timestamp "$QUOTE_TIME" --request-id trial-entry-001
stock-pilot status
```

Prices above are fabricated examples, not current RELIANCE prices. Then simulate an adverse quote:

```bash
QUOTE_TIME=$(python -c 'from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())')
stock-pilot paper-tick RELIANCE.NS --price 94 --timestamp "$QUOTE_TIME" --request-id trial-tick-001
stock-pilot status
```

A unique request ID makes retries return the original result rather than repeat a fill. Use a new ID for each new action. Reusing an ID returns its original action even if you change parameters. SQLite transactions protect cash and position updates; the ledger persists in `paper.db`.

```bash
stock-pilot pause
stock-pilot resume
```

Pause blocks new entries. Protection remains active **when you supply paper ticks**. The `watch` command continuously checks a quote-feed file while its process is running (see below). It can read an external feed or refresh public Yahoo data with `--source yahoo` (see above). Stops are local simulated rules, not broker-hosted stop orders. Daily loss rules block new entries; they do not liquidate every holding.

## Talk to your Manager

```bash
stock-pilot chat
stock-pilot chat "review my portfolio"
stock-pilot chat "pause trading"
stock-pilot chat "why RELIANCE.NS"
```

For broader explanations using your installed Ollama model:

```bash
stock-pilot chat --model qwen3:4b
```

The AI sees a bounded snapshot of paper holdings and up to three recent saved JSON reports. It has no execution tools, keeps only a short in-memory conversation, and can be wrong. Exact supported pause/resume commands remain deterministic. If Ollama fails, those commands still work.

In the interactive chat, type `help` for supported requests and `exit` to leave. Unrecognized instructions do nothing. The Manager never infers a buy or sell order from a chat message. It can show saved reports and explain their dates and ratings; their financial claims remain upstream-generated.

## Compare stocks

Save individual research results to separate files:

```bash
stock-pilot research RELIANCE.NS --date 2026-10-19 --output reports/reliance.json
stock-pilot research TCS.NS --date 2026-10-19 --output reports/tcs.json
stock-pilot compare reports/reliance.json reports/tcs.json --date 2026-10-19
```

Use the desired analysis date for all three commands. The comparison orders Buy, Overweight, Hold, Underweight and Sell ratings; equal ratings use alphabetical order. **This is an opinion ranking, not evidence that the first stock will perform best.** Reports must share the requested analysis date, have been generated within 24 hours, contain core reports, cite their source URLs and have dated, hash-checked snapshots attached. Financial evidence needs an allowed primary-domain source. Missing data and local protection objections move a stock to `needs_review`. URL presence does not verify the article, its publication date, or the underlying claim. Historical comparisons stay research-only.

## Automatic paper-market data

```bash
python -m pip install -e '.[market]'
stock-pilot collect RELIANCE.NS TCS.NS
stock-pilot watch --source yahoo --interval 30
```

`collect` writes `reports/quotes.json`. The Yahoo watcher refreshes quotes for currently held paper positions each cycle, then runs protection checks. It supports `.NS` / `.BO` symbols and verifies the returned symbol and INR currency. Quote price and time come from matching Yahoo metadata; fetch time is stored separately and never used to make an old price appear fresh. Feed writes are atomic.

Public Yahoo data can be delayed, unavailable, rate-limited or closed-market. It is not an execution-grade feed. Outside market hours, the most recent market timestamp will normally fail the quote-age check. A delayed quote pauses new paper entries rather than generating a fictitious timely exit. Collection errors are shown separately. Do not widen freshness limits just to make stale prices pass.

## Continuous paper protection

An external data collector must refresh a JSON file with real quote timestamps. The watcher never substitutes the current clock for an old quote. Example feed shape (values are fabricated):

```json
{
  "RELIANCE.NS": {"price": "94", "timestamp": "2026-10-19T22:30:00+00:00"}
}
```

Replace the timestamp with the real source quote time. Write updates to a temporary file and atomically rename it to `quotes.json`, so the watcher does not read a partially written file.

```bash
stock-pilot watch --feed quotes.json --interval 5
```

Run in a separate terminal from the Manager. It checks each held position, applies stop/trailing rules and stores simulated fills. `--cycles 1` runs one check and exits. Stale, missing, invalid or out-of-order held-position quotes pause new entries and report errors. Valid positions still receive protection checks while entries are paused. Resume is manual after the feed recovers. Monitoring ends if the process or machine stops; no broker-hosted protection exists in this version.

New entries require fresh marks for all existing positions and also obey maximum open positions (default 5) and total marked exposure (default 50000). These can be set using `max_open_positions` and `max_total_exposure` in the limits JSON. They are demonstration defaults, not personalized allocation advice.

## OpenAlgo connection check

Run your own [OpenAlgo](https://github.com/marketcalls/openalgo) installation and enable Analyzer Mode in its interface. Set the URL and API key in your shell; never commit keys.

```bash
export OPENALGO_URL=http://127.0.0.1:5000
read -rs -p 'OpenAlgo API key: ' OPENALGO_API_KEY
export OPENALGO_API_KEY
stock-pilot openalgo-check
```

Remote endpoints require HTTPS. The check refuses an unconfirmed or disabled analyzer mode. It never switches modes and has no order submission function. The local paper ledger is independent of OpenAlgo's sandbox. OpenAlgo market data may require broker credentials and data entitlements.

## Performance reports

[QuantStats](https://github.com/ranaroussi/quantstats) is an optional report integration:

```bash
python -m pip install -e '.[reports]'
stock-pilot report examples/net_returns.csv --output reports/performance.html
```

The sample CSV is fabricated. Supply sorted, unique dates and decimal periodic returns (`0.01` means 1%), already net of actual fees and slippage. Optional `benchmark` contains benchmark returns on the same dates. The ledger does not yet produce a time-series equity curve automatically.

## Installation health check

```bash
stock-pilot doctor
```

This checks Python, optional modules and local Ollama availability/model names. It does not download anything, expose API keys, or declare a market feed validated merely because a package is installed.

## Verification

```bash
python -m unittest discover -s tests -v
```

Tests cover gap losses, stop/trailing exits, fees, daily entry blocking, duplicate actions, persistence, pause behavior, invalid and stale prices, out-of-order ticks, continuous monitor cycles, re-entry identity, report comparison, Manager requests, portfolio exposure, the upstream adapter contract, and OpenAlgo mode verification. Mocked integrations do not establish live compatibility.

## Research and decision controls

v0.4 adds source snapshots, itemized costs, chronological holdout evaluation, sector/related-holdings caps, persisted marked-equity drawdown checks, deterministic `NO_TRADE` assessments, and a local decision/outcome journal.

Follow [the six-step research workflow](docs/RESEARCH_WORKFLOW.md) for commands, required inputs and limitations. Synthetic examples and passing tests do not establish a tradable edge.

v0.5 also adds sequential agency coordination with durable steps and current-risk revalidation, five synthetic local-model evaluation tasks, immutable investment theses and reviews, disjoint-period evaluation suites, and normalized broker-export reconciliation. The reconciliation module is not a live broker connection.

## Next implementation gates

- Validate upstream installation, local-model tool calling, and Indian company/news coverage on the target server.
- Verify sources and publication times independently; keep unverified research out of actionable recommendations.
- Validate local-model answers on the target server; add investment timeframes and suitability inputs.
- Validate Yahoo availability/delay during market hours or connect a broker data source; validate marked equity history and reviewed sector/group classifications.
- Backtest on unseen data with Indian costs, then test broker sandbox execution including partial fills and reconnects.
- Only after broker selection, explicit limits, authorization and validation: implement live execution, broker-side protection and reconciliation.

No real money was connected or traded while building these versions.
