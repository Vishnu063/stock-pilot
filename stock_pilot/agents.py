"""Five user-facing roles; reuse upstream research instead of duplicating LLM agents."""
from copy import deepcopy
from datetime import datetime, timezone
import re

ROLES = {
    "strategy": "TradingAgents market analyst and trader proposal",
    "protection": "Deterministic limits and paper-position stop checks",
    "research": "TradingAgents news and fundamentals analysts",
    "manager": "Coordinates reports, status, pause and resume; no broker execution",
    "investment": "Combines upstream final assessment with local protection review",
}


def research(symbol, as_of, config_path):
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.&^_-]{0,30}(?:\.(?:NS|BO))?", symbol):
        raise ValueError("Invalid symbol")
    import json
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    config = deepcopy(DEFAULT_CONFIG)
    with open(config_path) as f:
        overrides = json.load(f)
    config.update(overrides)
    graph = TradingAgentsGraph(selected_analysts=["market", "news", "fundamentals"], config=config)
    state, rating = graph.propagate(symbol, as_of)
    reports = {key: state.get(key, "") for key in (
        "market_report", "news_report", "fundamentals_report", "investment_plan",
        "trader_investment_plan", "final_trade_decision")}
    missing = [key for key, value in reports.items() if not isinstance(value,str) or not value.strip()]
    return {"symbol":symbol,"as_of":as_of,"generated_at":datetime.now(timezone.utc).isoformat(),
            "rating":rating if not missing else "REVIEW", "reports":reports,
            "missing_reports":missing,"execution_allowed":False,
            "evidence_status":"Upstream citations retained in reports; source completeness and freshness require review"}


def investment_review(report, status, limits):
    blocked = []
    if status["paused"]:
        blocked.append("Manager paused entries")
    from .risk import money
    if money(status["loss_guard_pnl"]) <= -limits.daily_loss_limit:
        blocked.append("Daily loss limit reached")
    if report.get("missing_reports") or report.get("rating") not in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        blocked.append("Incomplete or unrecognized research")
    return {"research_rating":report.get("rating", "REVIEW"), "protection_objections":blocked,
            "manager_verdict":"REVIEW" if blocked else "RESEARCH_ONLY",
            "note":"No ranking across stocks, suitability assessment, or automatic purchase in v0.1",
            "next":"Review source evidence, timeframe, current quote, quantity and stop before any paper entry"}
