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


# v0.5 agency integration

The current automated suite passes 79 tests. Added tests cover checkpoint recovery, crash-after-final-commit idempotency, changed-input rejection, active leases, current Manager eligibility after a pause, refusing stale fallback after a quote failure, synthetic model-scoring checks, thesis invalidation/stale facts, disjoint evaluation periods, retained failed jobs, partial fills, unconfirmed orders, rejected protection, duplicate IDs, outstanding entries, account mismatch and oversell coverage.

The actual local-model evaluation command was attempted. Ollama was unreachable; all five requests returned connection errors. No claim about Qwen answer quality or financial readiness follows from that result. Full live research, market-data availability, target-server memory/latency and authenticated broker reconciliation remain unverified.

All coordination, fills used in tests, thesis observations and exported broker snapshots were synthetic. The coordinator has no order-submission path. The broker integration is a normalized read-only file interface pending broker selection.
