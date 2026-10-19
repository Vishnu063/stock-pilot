"""Deterministic no-trade gates. Passing means a PAPER candidate, never a live order."""

from datetime import datetime
from uuid import uuid4
from .manager import evidence_check
from .risk import money, positive, quantity


def assess(report, proposal, broker):
    reasons = []
    preview = None
    reward_risk = None
    symbol = proposal.get("symbol")
    if symbol != report.get("symbol"):
        reasons.append("Proposal and research refer to different stocks")
    as_of = report.get("as_of", "")
    try:
        reasons.extend(evidence_check(report, as_of)["problems"])
    except (ValueError, TypeError):
        reasons.append("Invalid research analysis date")
    if report.get("rating") not in ("Buy", "Overweight"):
        reasons.append("Research does not support a new long position")
    if broker.cost_schedule is None or not broker.cost_schedule.reviewed:
        reasons.append("No reviewed itemized cost schedule configured")
    if broker.limits.max_drawdown_pct is None:
        reasons.append("Portfolio drawdown limit has not been configured")
    if (
        broker.limits.max_sector_exposure is None
        or broker.limits.max_group_exposure is None
    ):
        reasons.append("Sector and related-holdings limits have not been configured")
    if any(
        value is None
        for value in (
            broker.limits.min_daily_turnover,
            broker.limits.max_spread_bps,
            broker.limits.min_reward_risk,
        )
    ):
        reasons.append(
            "Liquidity, spread and reward/risk policy thresholds are not configured"
        )
    try:
        days = proposal["holding_days"]
        if type(days) is not int or not 1 <= days <= 3650:
            raise ValueError("Holding period must be a whole number of days")
        quote = proposal["quote"]
        if (
            quote.get("currency") != "INR"
            or not isinstance(quote.get("source"), str)
            or not quote["source"].strip()
        ):
            raise ValueError("Quote requires INR currency and named source")
        quote_time = datetime.fromisoformat(quote["timestamp"])
        from zoneinfo import ZoneInfo

        if as_of != quote_time.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat():
            raise ValueError(
                "Research and quote market dates differ; refresh the analysis"
            )
        # These observed liquidity inputs must come from a reviewed collector.
        turnover = positive(proposal["average_daily_turnover"])
        if turnover < positive(broker.limits.min_daily_turnover):
            reasons.append(
                "Average turnover is below the configured liquidity threshold"
            )
        spread = money(proposal["spread_bps"])
        if spread < 0 or spread > positive(broker.limits.max_spread_bps):
            reasons.append("Spread is invalid or exceeds the configured threshold")
        qty = quantity(proposal["quantity"])
        target = positive(proposal["target"])
        stop = positive(proposal["stop"])
        preview = broker.buy(
            symbol,
            qty,
            quote["price"],
            quote["timestamp"],
            stop,
            "preview:" + str(uuid4()),
            proposal.get("trailing_pct"),
            preview=True,
        )
        entry = money(preview["entry_fill"])
        fees = money(preview["costs"]["total"])
        exit_stop = broker.limits.fill(stop, "SELL")
        target_fill = broker.limits.fill(target, "SELL")
        stop_fees = money(preview["stop_exit_cost"])
        target_fees = money(broker.costs(target_fill, qty, "SELL")["total"])
        loss = (entry - exit_stop) * qty + fees + stop_fees
        reward = (target_fill - entry) * qty - fees - target_fees
        required = positive(broker.limits.min_reward_risk)
        if loss <= 0 or reward <= 0:
            reasons.append("Target does not offer positive net reward after costs")
        else:
            reward_risk = reward / loss
            if reward_risk < required:
                reasons.append("Net reward-to-risk is below the configured threshold")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        reasons.append(str(exc))
    return {
        "symbol": symbol,
        "decision": "NO_TRADE" if reasons else "PAPER_CANDIDATE",
        "reasons": list(dict.fromkeys(reasons)),
        "preview": preview,
        "net_reward_risk": str(reward_risk) if reward_risk is not None else None,
        "holding_days": proposal.get("holding_days"),
        "execution_allowed": False,
        "note": "Targets and liquidity inputs are supplied assumptions, not verified forecasts; no automatic execution",
    }
