"""Small, auditable daily-bar SMA evaluation. Model opinions never become historical labels.

Parameters are selected on the chronological training slice only. The holdout is
reported once without tuning. This is a baseline research strategy, not a profit claim.
"""

import csv
import hashlib
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
from .risk import money, positive


def load_bars(path):
    raw = Path(path).read_bytes()
    bars = []
    with io.StringIO(raw.decode("utf-8-sig"), newline="") as f:
        for row in csv.DictReader(f):
            when = date.fromisoformat(row["date"])
            if when > date.today() or (bars and when <= bars[-1]["date"]):
                raise ValueError(
                    "Bar dates must be past/present, unique and increasing"
                )
            bar = {
                "date": when,
                **{k: positive(row[k]) for k in ("open", "high", "low", "close")},
                "volume": money(row["volume"]),
            }
            if (
                bar["volume"] < 0
                or bar["low"] > min(bar["open"], bar["close"])
                or bar["high"] < max(bar["open"], bar["close"])
                or bar["low"] > bar["high"]
            ):
                raise ValueError("Invalid OHLC or volume")
            bars.append(bar)
    return bars, hashlib.sha256(raw).hexdigest()


def simulate(
    bars,
    start,
    end,
    fast,
    slow,
    schedule,
    capital="100000",
    allocation="0.2",
    slippage_bps="10",
    stop_pct="5",
    buy_hold=False,
    max_volume_fraction="0.01",
):
    participation = positive(max_volume_fraction)
    if participation > 1:
        raise ValueError("Volume participation must be in (0, 1]")
    capital = positive(capital)
    allocation = positive(allocation)
    slippage = money(slippage_bps)
    stop_pct = positive(stop_pct)
    if not 0 < allocation <= 1 or not 0 <= slippage < 10000 or stop_pct >= 100:
        raise ValueError("Invalid simulation settings")
    if (
        type(fast) is not int
        or type(slow) is not int
        or not 0 < fast < slow
        or start < slow
        or not start < end <= len(bars)
    ):
        raise ValueError("Invalid moving-average windows or evaluation boundaries")
    cash, shares, entry, entry_fee = capital, 0, Decimal(0), Decimal(0)
    peak = capital
    drawdown = Decimal(0)
    events = []
    equity = []
    closed = 0
    wins = 0
    position_pnl = Decimal(0)
    exit_pending = False
    capacity = 0
    orders = []

    def trade(side, price, requested, bar, reason):
        nonlocal cash, shares, entry, entry_fee, closed, wins, capacity, position_pnl
        qty = min(requested, capacity)
        orders.append({
            "date": bar["date"].isoformat(), "side": side, "reason": reason,
            "requested_quantity": requested, "filled_quantity": qty,
            "unfilled_quantity": requested - qty,
            "status": "FILLED" if qty == requested else "PARTIAL" if qty else "UNFILLED",
        })
        if not qty:
            return
        capacity -= qty
        fill = price * (1 + slippage / 10000 if side == "BUY" else 1 - slippage / 10000)
        costs = money(schedule.calculate(fill, qty, side, bar["date"].isoformat())["total"])
        if side == "BUY":
            cash -= fill * qty + costs
            shares = qty
            entry = fill
            entry_fee = costs
            position_pnl = Decimal(0)
            pnl = None
        else:
            allocated_entry_fee = entry_fee * qty / shares
            cash += fill * qty - costs
            pnl = (fill - entry) * qty - allocated_entry_fee - costs
            entry_fee -= allocated_entry_fee
            shares -= qty
            position_pnl += pnl
            if not shares:
                closed += 1
                wins += int(position_pnl > 0)
        events.append({
            "date": bar["date"].isoformat(), "side": side, "fill": str(fill),
            "quantity": qty, "fees": str(costs), "reason": reason,
            "net_pnl": str(pnl) if pnl is not None else None,
        })

    for i in range(start, end):
        bar = bars[i]
        # Whole-day volume is an ex-post capacity bound, not opening liquidity.
        capacity = int(bar["volume"] * participation)
        exited_today = False
        # Excludes today's close entirely. Signal known before today's opening auction.
        past = [b["close"] for b in bars[i - slow : i]]
        want_long = buy_hold or (sum(past[-fast:]) / fast > sum(past) / slow)
        if shares and (exit_pending or not want_long):
            trade("SELL", bar["open"], shares, bar, "pending_exit" if exit_pending else "prior_close_signal")
            exit_pending = bool(shares)
            exited_today = True
        if not shares and not exited_today and want_long and (not buy_hold or i == start):
            estimated = bar["open"] * (1 + slippage / 10000)
            budget = min(cash, capital * allocation)
            qty = int(budget / estimated)
            while (
                qty > 0
                and estimated * qty
                + money(
                    schedule.calculate(estimated, qty, "BUY", bar["date"].isoformat())[
                        "total"
                    ]
                )
                > budget
            ):
                qty -= 1
            if qty > 0:
                trade("BUY", bar["open"], qty, bar, "prior_close_signal")
        if shares and not buy_hold and not exited_today:
            stop = entry * (1 - stop_pct / 100)
            if bar["low"] <= stop:
                trade(
                    "SELL", min(bar["open"], stop), shares, bar, "gap_or_intrabar_stop"
                )
                exit_pending = bool(shares)
        if shares and i == end - 1:
            trade("SELL", bar["close"], shares, bar, "predeclared_end_liquidation")
        mark = cash + shares * bar["close"]
        peak = max(peak, mark)
        drawdown = max(drawdown, (peak - mark) / peak)
        equity.append({"date": bar["date"].isoformat(), "equity": str(mark)})
    equity_value = cash + shares * bars[end - 1]["close"]
    return {
        "ending_equity": str(equity_value),
        "ending_shares": shares,
        "unrealized_pnl": str((bars[end - 1]["close"] - entry) * shares - entry_fee) if shares else "0",
        "orders": orders,
        "max_volume_fraction": str(participation),
        "net_return": str((equity_value - capital) / capital),
        "max_drawdown": str(drawdown),
        "closed_trades": closed,
        "winning_trades": wins,
        "ending_cash": str(cash),
        "events": events,
        "equity": equity,
    }


def evaluate(
    path,
    schedule,
    split_date,
    candidates=None,
    allocation="0.2",
    slippage_bps="10",
    stop_pct="5",
    benchmark_path=None,
    holdout_end=None,
    max_volume_fraction="0.01",
):
    bars, digest = load_bars(path)
    from .data_quality import inspect_dataset

    data_quality = inspect_dataset(path, bars, digest)
    if holdout_end is not None:
        end = date.fromisoformat(holdout_end)
        if end < date.fromisoformat(split_date):
            raise ValueError("Holdout end precedes split date")
        bars = [bar for bar in bars if bar["date"] <= end]
    candidates = candidates or [(5, 20), (10, 30)]
    if len(candidates) > 10:
        raise ValueError("At most ten declared training trials")
    split = next(
        (i for i, b in enumerate(bars) if b["date"] >= date.fromisoformat(split_date)),
        len(bars),
    )
    warmup = max(slow for _, slow in candidates)
    if split - warmup < 30 or len(bars) - split < 30:
        raise ValueError(
            "Require at least 30 evaluated training and 30 holdout bars after warmup"
        )
    # Validate cost coverage across the entire dataset before choosing any strategy.
    if bars[0]["date"] < schedule.start or bars[-1]["date"] > schedule.end:
        raise ValueError("Historical costs do not cover this dataset")
    options = {
        "allocation": allocation,
        "slippage_bps": slippage_bps,
        "stop_pct": stop_pct,
        "max_volume_fraction": max_volume_fraction,
    }
    trials = []
    for fast, slow in candidates:
        result = simulate(bars, warmup, split, fast, slow, schedule, **options)
        trials.append(
            {
                "fast": fast,
                "slow": slow,
                "training_net_return": result["net_return"],
                "training_drawdown": result["max_drawdown"],
            }
        )
    chosen = max(trials, key=lambda r: money(r["training_net_return"]))
    test = simulate(
        bars, split, len(bars), chosen["fast"], chosen["slow"], schedule, **options
    )
    baseline = simulate(
        bars,
        split,
        len(bars),
        chosen["fast"],
        chosen["slow"],
        schedule,
        buy_hold=True,
        **options,
    )
    benchmark = None
    if benchmark_path is not None:
        benchmark_bars, benchmark_hash = load_bars(benchmark_path)
        mapping = {bar["date"]: bar for bar in benchmark_bars}
        if any(bar["date"] not in mapping for bar in bars[split:]):
            raise ValueError("Benchmark dates must cover every holdout bar")
        first = mapping[bars[split]["date"]]["open"]
        last = mapping[bars[-1]["date"]]["close"]
        benchmark = {
            "data_quality": inspect_dataset(benchmark_path, benchmark_bars, benchmark_hash),
            "dataset_sha256": benchmark_hash,
            "full_exposure_price_return": str((last - first) / first),
            "note": "Reference price series only; no dividends or fees inferred. Strategy capital allocation is reported separately.",
        }
    return {
        "data_quality": data_quality,
        "benchmark_reference": benchmark,
        "dataset_sha256": digest,
        "split_date": split_date,
        "holdout_end": bars[-1]["date"].isoformat(),
        "training_trials": trials,
        "selected_on_training_only": {"fast": chosen["fast"], "slow": chosen["slow"]},
        "holdout": test,
        "same_stock_buy_hold_baseline": baseline,
        "settings": options,
        "costs_reviewed": schedule.reviewed,
        "execution_allowed": False,
        "limitations": [
            "Daily volume participation is an ex-post bound, not opening/stop liquidity or an exchange execution model",
            "Unfilled entries are cancelled; incomplete exits retry next bar; terminal residuals stay marked at close",
            "No circuit-limit, queue, intraday path or market-session execution simulation",
            "Corporate actions, survivorship and source authenticity must be independently checked",
            "This fixed holdout becomes contaminated if used to tune later versions",
            "A single-stock result does not establish a general or profitable strategy",
        ],
    }
