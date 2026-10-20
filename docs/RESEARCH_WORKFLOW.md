# Research workflow — v0.4

These six controls improve research discipline. They do not establish a profitable strategy or verify external data. All example numbers are synthetic, not personal risk recommendations.

## 1. Preserve evidence

Fill in `examples/evidence.manifest.template.json` with actual document URLs, local snapshots, publication and capture times:

```bash
stock-pilot attach-evidence reports/research.json source-manifest.json --output reports/research-with-evidence.json
```

Timestamps require timezones. Publication must precede capture and the end of the analysis date in Asia/Kolkata. Capture cannot be in the future. Snapshots are copied and hashed. Comparison checks the copy, dates, symbol and URL citation in the corresponding report section. It requires dated news evidence and financial evidence from an NSE, BSE or SEBI domain. Domain suffix lookalikes are rejected.

This conservative allowlist excludes company investor-relations domains for now. Domain matching does not prove the supplied file came from that URL. Hashes prove consistency, not authenticity, truth or completeness. A historical publication label does not establish that a document has never been revised. No model-supplied URL is fetched automatically.

Primary entry points:

- https://www.nseindia.com/companies-listing/corporate-filings-announcements
- https://www.nseindia.com/companies-listing/corporate-filings-financial-results
- https://www.nseindia.com/companies-listing/corporate-filings-annual-reports

Use actual filing URLs, not generic index pages. Whether a source supports a specific claim still requires review.

## 2. Itemize costs

`--costs` loads an effective-dated JSON schedule. Each charge has a unique `name`, `side` (BUY/SELL/BOTH), optional turnover `rate_bps`, `fixed` amount, per-order `cap`, `gst_pct`, and `round_to` increment. One basis point is 0.01%. Paper entries, stop-loss planning, target reward and realized P&L use the same calculator as the backtest. Slippage changes fill prices separately.

`examples/costs.synthetic.json` is an arithmetic fixture, not a real brokerage tariff. Its unreviewed flag prevents passing trade assessments. An actual schedule must include all applicable brokerage, STT, exchange and SEBI charges, stamp duty, DP charges and taxes. `reviewed: true` is an operator declaration after checking the relevant broker and effective dates, not automatic verification.

This engine models per-order costs. Daily aggregate rounding, DP fees charged once per instrument/day, broker minimums and all broker-specific rules are not automatically covered. Calibrate estimates against contract notes. Broker is currently undecided.

Reference entry points: https://zerodha.com/charges/ and https://zerodha.com/brokerage-calculator/

Global arguments precede commands:

```bash
stock-pilot --costs reviewed-costs.json status
```

Without a schedule, manual paper exercises retain a flat fee and cannot pass the research-assessment gate.

## 3. Chronological holdout evaluation

Supply sorted CSV columns `date,open,high,low,close,volume`. Independently verify corporate actions, missing sessions, delistings and provenance.

```bash
stock-pilot --costs historical-costs.json backtest bars.csv --split-date 2025-07-01 --benchmark index-bars.csv
```

Two declared SMA candidates, 5/20 and 10/30, are selected on training net return only. At least 30 evaluated training bars after warmup and 30 holdout bars are required. Signals use prior completed closes; entry is at the following open. A gap through the stop exits at the opening price, otherwise a crossed daily low uses the stop threshold. Final liquidation at the last evaluation close is predeclared. Fees and slippage are deducted.

This is a daily-bar baseline, not an AI predictor or an exchange emulator. It does not model partial fills, circuit-limit execution, volume-limited fills or an exchange calendar. Allocation and stop defaults are demonstration assumptions. A single effective-dated cost schedule must cover the data; tariff changes inside an interval are not supported yet.

Reports retain every training trial, holdout equity/trades and a same-stock buy-and-hold baseline. An optional reference index reports full-exposure price return without inferred dividends or fees; compare allocation and definitions carefully. Repeat dataset hashes are flagged in the journal. Editing files or repeatedly trying splits can still contaminate a holdout. There is no automatic strategy promotion or retraining.

## 4. Portfolio concentration and drawdown

Optional limits keys are `max_sector_exposure`, `max_group_exposure` (absolute account-currency caps) and `max_drawdown_pct`. Supply reviewed classifications with `--instruments instruments.json`; a shape template is included.

Related-holdings groups are manually reviewed labels, not an estimated correlation matrix. Missing classifications block entries when caps are enabled. New entries need fresh marks for all held positions. Cash plus marked holdings determines equity. A persisted peak supports entry-blocking drawdown checks; resume cannot bypass the limit. It does not liquidate all positions or guarantee losses stop there.

Existing database holdings/cash are preserved. Because old versions did not track peaks, migration initializes the peak to current marked equity; past peak drawdown cannot be reconstructed.

## 5. Deterministic no-trade decisions

Replace every placeholder and market observation in `examples/proposal.template.json`:

```bash
stock-pilot --costs reviewed-costs.json --instruments instruments.json --limits limits.json assess reports/research-with-evidence.json proposal.json
```

Set `min_daily_turnover`, `max_spread_bps` and `min_reward_risk` in the operator-controlled limits JSON. Proposal values cannot override those thresholds. The gate checks source integrity/dates, Buy/Overweight opinion, reviewed costs, configured portfolio limits, fresh INR source quote, matching research/market date, holding period, turnover/spread thresholds, affordability, exposure and net target reward-to-risk.

Liquidity, target and classifications remain supplied assumptions. Target reward/risk is not expected value or a success probability. Passing returns `PAPER_CANDIDATE`; objections return `NO_TRADE`. Neither places an order. Manual `paper-buy` remains a simulator exercise that enforces core risk checks but bypasses this research gate. Chat cannot turn a rating into an order.

## 6. Decision and outcome journal

```bash
stock-pilot journal --verify
stock-pilot journal --summary
stock-pilot chat "show performance"
stock-pilot observe DECISION_ID --price 110 --timestamp SOURCE_TIMESTAMP --reason "Explain what changed"
```

Assessments retain research, proposal and horizon. User-supplied follow-up prices are observations, not broker-confirmed fills. Follow-ups to rejected ideas are counterfactual and excluded from realized-profit summaries. Paper SELL records link position IDs and net P&L after entry/exit costs. Pre-journal events are not backfilled.

A hash chain detects modified entries given a trusted checkpoint. A local administrator can rewrite or truncate it; keep the head hash elsewhere for independent auditing. Evaluations never modify strategy rules or model weights automatically.

## User constraints

Days-to-months positions, 8 GB target server, broker undecided. Qwen is configured through Ollama. Run research jobs sequentially and configure one loaded model/parallel request on the Ollama server if memory is constrained. Target-machine resource usage remains unverified. Capital, personal loss limits and live authorization are unset.

## Historical data checks (v0.6.1)

Before evaluating a CSV, run:

```bash
python -m stock_pilot data-check bars.csv
```

This command needs no costs, model or paper account. Exit code 1 means review is
needed (or the input is invalid); 0 means declared checks passed, never trading
permission. Backtest reports automatically include `data_quality` for both the
stock and an optional benchmark. Existing CSV-only backtests still run, explicitly
marked `NEEDS_REVIEW`; diagnostics do not change their simulated returns.

An optional `bars.csv.metadata.json` describes the **complete CSV**, including
warmup/training dates, even when a shorter holdout end is requested:

```json
{
  "schema_version": 1,
  "dataset_sha256": "REPLACE_WITH_SHA256_OF_EXACT_CSV_BYTES",
  "symbol": "RELIANCE.NS",
  "currency": "INR",
  "source_url": "https://example.com/replace-with-actual-source",
  "captured_at": "2026-10-20T10:00:00+00:00",
  "price_basis": "raw",
  "corporate_actions_reviewed": false,
  "corporate_actions": [],
  "expected_sessions": ["2025-01-02", "2025-01-03"]
}
```

Supply the actual exchange sessions for the whole file, including exceptional
sessions and holidays. No weekday-only calendar is inferred. The checksum can be
obtained with `sha256sum bars.csv`. A checksum mismatch, invalid capture time, or
invalid metadata stops evaluation. Missing/extra sessions, zero-volume bars and
absolute overnight moves over 25% require review. A large move may be real; this
threshold is diagnostic, not an exchange price limit.

Only raw bars with an explicitly reviewed declaration of no corporate actions
can pass these declared checks. Adjusted prices or declared actions require review
because this simulator does not implement their cash/share accounting. Do not
label adjusted bars as raw or remove actions to clear a warning. These declarations
are not authenticated by the program, and neither source authenticity nor
survivorship bias is established. It performs no automatic price correction.
