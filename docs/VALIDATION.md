# Validation record — v0.3

Validated in an isolated Python 3.12 environment on 2026-10-20.

| Check | Result |
|---|---|
| Offline synthetic demo | Passed |
| Unit and simulated integration tests | 37 passed |
| Optional research and reporting installation | Passed; pinned TradingAgents 0.7.0 installed |
| Dependency consistency (`pip check`) | Passed |
| TradingAgents graph import | Passed |
| QuantStats sample HTML generation | Passed; system fell back from missing Arial font |
| Yahoo RELIANCE.NS request | Failed: no usable chart metadata; command returned nonzero, no fabricated quote |
| Local Ollama availability | No running service/model detected |
| Full LLM research and conversation | Not validated without a running local model |
| OpenAlgo server | Not connected; API contract and rejection behavior tested with mocks |
| Live orders | Not implemented or attempted |

Installed test versions included yfinance 1.7.0, QuantStats 0.0.86 and TradingAgents at the pinned commit recorded in `pyproject.toml`. Installation exposed a missing SOCKS support dependency in the proxied environment; `httpx[socks]` is now included in the research extra.

Tests exercise source timestamp preservation, wrong symbol/currency rejection, partial collection errors, atomic feed writes, automatic paper-monitor wiring, feed-write failure handling, and read-only local chat. Mocked success does not establish live vendor availability or model accuracy.

No profitability, execution latency, target-server resource usage, source factual accuracy or trading suitability has been established by these checks.


# v0.4 controls

The sequential upgrades add local source integrity/date checks, configurable itemized costs, daily-bar chronological holdout testing, sector/group and persisted drawdown gates, no-trade assessment, and a local hash-linked journal. No previously failed market-data or model check is treated as resolved by these changes.

The current suite passes 58 tests, including source tampering, future publications, domain spoofing, itemized fee/cash reconciliation, holdout isolation, prior-close signal timing, concentration/drawdown blocking, assessment non-execution, audit modification detection, counterfactual outcome labeling and v0.3 database migration.

Recorded user constraints: days-to-months holding style, 8 GB target server and broker undecided. Capital and personal risk limits remain unset. No live orders are implemented.
