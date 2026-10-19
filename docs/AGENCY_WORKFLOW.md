# Agency workflow — v0.5

This release coordinates the five existing roles. It still cannot submit paper entries or live broker orders automatically. A successful workflow may correctly conclude NO_TRADE.

## Start without accounts or a model

```bash
python -m stock_pilot.cli agency-demo
```

All inputs are synthetic. The demo displays strategy, research, protection, investment and Manager outputs, including disagreement when a bullish opinion fails risk checks. Missing evidence and policies deliberately produce NO_TRADE. This is a workflow demonstration, not a profitable trading demonstration.

## Run an actual research job

Copy `examples/agency.job.template.json`, replace the symbol, analysis date, proposal and quote observations, and configure reviewed costs, limits and instrument classifications as described in [the research workflow](RESEARCH_WORKFLOW.md).

```bash
stock-pilot --costs reviewed-costs.json --limits limits.json --instruments instruments.json agency job.json --run-id research-001
stock-pilot agency-status research-001
stock-pilot chat "agency status"
```

The coordinator runs sequentially:

1. Read a saved report or call TradingAgents once for market, trader, news and fundamentals outputs.
2. Attach source snapshots if `evidence_manifest` is supplied.
3. Optionally register a thesis and compare normalized broker snapshots.
4. Apply deterministic protection checks.
5. Combine the research opinion with risk objections; protection takes precedence.
6. Journal the Manager's assessment and return all five role outputs.

Set `saved_report` to use existing research; leave it null for a model run. `research_config` is the existing TradingAgents configuration file. Saved reports must match the job's instrument/date. A newly generated report without reviewed source snapshots remains insufficient for a candidate. The pipeline does not independently authenticate sources or company facts.

`quote_source` is `supplied` by default. Set it to `yahoo` to collect a new public quote after research and on each resume, instead of using the proposal's old quote. The collector must be installed. If collection fails, the old price is never substituted; the result is NO_TRADE. Public quotes may be delayed or unavailable and remain paper-testing data.

The top-level Manager and protection outputs reflect current revalidation. `historical_manager` preserves the originally checkpointed decision. A completed cached run can return NO_TRADE now if cash, holdings, pause state, evidence integrity or quote age changed. It does not silently reuse old eligibility.

### Recovery behavior

Completed step outputs are stored in SQLite. Repeat the same command and run ID after a failed run to resume. Changes to the job, referenced configuration/report/manifest files, manifest snapshots, risk/cost configuration, instrument classifications or engine version require a new run ID. Input changes detected while a task runs prevent its commit.

An active lease prevents a second worker from taking the same run. Default lease: one hour; `--lease-seconds` adjusts it, with a minimum of 60 seconds. After a hard process kill, recovery must wait for expiry. A model task taking longer than its lease cannot commit. Configure enough time for CPU inference and keep research jobs sequential on the 8 GB target.

A task interrupted before its output is checkpointed can run again. Read/model calls and upstream logs may therefore repeat. This is not exactly-once external execution. The final Manager journal entry and checkpoint commit in one transaction, so retrying after that commit does not duplicate that decision. No order submission happens anywhere in this coordinator.

## Evaluate Qwen on the target machine

```bash
stock-pilot evaluate-model --model qwen3:4b
```

The command asks five synthetic tasks: exact company identity, fee arithmetic, missing-data abstention, citation fidelity and ignoring an untrusted instruction. Output includes each answer/error, total passes and timestamps. Nonzero exit status means at least one task did not pass. If all requests error, status is UNAVAILABLE; this is not evidence that Qwen answered the questions incorrectly.

The suite is deliberately small. Passing it does not establish financial expertise, news accuracy, broad injection resistance, investment skill or profitability. It does not enable trading. The model endpoint must be running locally. Tests use injected answers to validate scoring; those are not actual Qwen evaluations.

## Track why a position is held

Fill in `examples/thesis.template.json` with your actual rationale, holding period, review date, metric-based invalidation rules and verified upcoming events.

```bash
stock-pilot thesis add thesis.json --id thesis-001
stock-pilot thesis list
stock-pilot thesis review thesis-001 reviewed-facts.json
```

Rules support `lt`, `le`, `gt`, `ge` against numeric thresholds. Facts need the same symbol, a source observation timestamp and `source_reviewed: true`. This flag is a human/operator declaration, not independent verification. Missing metrics or observations older than `max_fact_age_days` (default 120) produce INSUFFICIENT_DATA. Breached rules produce THESIS_INVALIDATED. Due review dates and events within three days are reported.

Definitions are immutable; revised rules need a new thesis ID. Creation is idempotent for the same ID/definition. Reviews and inputs are journaled. A job can include a `thesis` object; its stable ID becomes `agency:RUN_ID`. This records a watchlist thesis even if no position is purchased. Thesis review never sells a holding or changes stop rules automatically.

## Test multiple stocks and periods

Copy `examples/evaluation-suite.template.json` and fill in datasets and predeclared split/end dates:

```bash
stock-pilot --costs historical-costs.json backtest-suite suite.json
```

Each job performs its own chronological train/holdout selection using the existing daily-bar model. Same-stock holdout windows must not overlap. All declared completed runs, losses and failures remain visible. The report includes per-run benchmark references when supplied, trial count, positive holdout count and descriptive return range/median.

These statistics are not a portfolio return or confidence interval. Cross-stock dependence, selection across multiple trials and survivorship are not statistically corrected. There is no deflated Sharpe calculation or automatic strategy promotion. Repeated dataset hashes are counted across individual and suite commands, but editing files or selecting favorable dates can still contaminate evaluation. Tests prove mechanics with synthetic bars; they do not establish an economic edge.

## Reconcile normalized broker exports

The broker is undecided, so this release supplies a read-only file adapter and normalized contract rather than a live broker connection. Templates define expected and observed snapshots. Supply complete snapshots from an authenticated adapter/export later; do not compare synthetic paper positions with an unrelated live account.

```bash
stock-pilot reconcile expected.json observed.json
stock-pilot reconcile expected.json observed.json --pause-on-mismatch
```

Instrument IDs are `EXCHANGE:SYMBOL:PRODUCT`. Orders include stable client ID, broker order ID, side, total and filled quantities, normalized status, purpose/type and protective trigger where relevant. Snapshot timestamps must be timezone-aware and current. A matching result remains read-only and does not authorize trading.

Checks cover account mismatch (when an expected account ID is provided), position differences, duplicate identities, unconfirmed/unexpected orders, invalid or unknown statuses, partial-fill consistency, outstanding entry quantity, rejected/cancelled/expired expected orders, insufficient stop coverage, oversell risk and orphan stops. An order ID is never treated as proof of execution. CLI mismatch status is nonzero; only the explicit pause flag changes local paper-entry pause state.

For a partial protective sell, coverage counts only the unfilled quantity against the remaining held quantity. Open/partial buy orders require review because remaining fills can increase exposure. Long-only whole-share positions and simple stops are supported; OCO, conditional broker orders and broker-specific semantics are not modeled. Caller-supplied snapshots are not authenticated by this module.

A job can set both `expected_snapshot` and `observed_snapshot`. Discrepancies force NO_TRADE. Snapshots are rechecked on resume and their file contents are fingerprinted; changed files require a new run ID. No automatic resubmit, cancel, repair or protective-order creation is performed.

## Remaining live-validation gates

Run Qwen and the complete research workflow on the target 8 GB server; obtain reliable market prices and reviewed evidence; choose a broker and implement its authenticated read-only adapter; verify costs and personal capital/loss limits. Then perform extended paper and sandbox validation before any separate live-order implementation. No profits, latency targets or production readiness are established by unit tests.
