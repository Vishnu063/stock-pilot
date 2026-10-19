"""Agent 2. Pure deterministic checks; language models cannot change these rules."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def money(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a price")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid numeric value") from exc
    if not result.is_finite():
        raise ValueError("Numbers must be finite")
    return result


def positive(value):
    result = money(value)
    if result <= 0:
        raise ValueError("Value must be positive")
    return result


def quantity(value):
    result = positive(value)
    if result != result.to_integral_value():
        raise ValueError("Quantity must be a positive whole number")
    return int(result)


@dataclass(frozen=True)
class Limits:
    max_position_value: Decimal
    max_trade_loss: Decimal
    daily_loss_limit: Decimal
    max_quote_age_seconds: int = 60
    slippage_bps: Decimal = Decimal("10")
    fee_per_order: Decimal = Decimal("0")
    max_total_exposure: Decimal = Decimal("50000")
    max_open_positions: int = 5
    max_sector_exposure: Decimal | None = None
    max_group_exposure: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    min_daily_turnover: Decimal | None = None
    max_spread_bps: Decimal | None = None
    min_reward_risk: Decimal | None = None

    def __post_init__(self):
        for name in (
            "max_position_value",
            "max_trade_loss",
            "daily_loss_limit",
            "max_total_exposure",
        ):
            object.__setattr__(self, name, positive(getattr(self, name)))
        for name in ("slippage_bps", "fee_per_order"):
            value = money(getattr(self, name))
            if value < 0 or (name == "slippage_bps" and value >= 10000):
                raise ValueError("Invalid fee or slippage")
            object.__setattr__(self, name, value)
        for name in ("max_sector_exposure", "max_group_exposure", "max_drawdown_pct", "min_daily_turnover", "max_spread_bps", "min_reward_risk"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, positive(value))
        if self.max_drawdown_pct is not None and self.max_drawdown_pct >= 100:
            raise ValueError("Drawdown limit must be below 100 percent")
        if type(self.max_open_positions) is not int or self.max_open_positions < 1:
            raise ValueError("Maximum open positions must be positive")
        if (
            type(self.max_quote_age_seconds) is not int
            or self.max_quote_age_seconds <= 0
        ):
            raise ValueError("Quote age must be positive whole seconds")

    @classmethod
    def load(cls, data):
        return cls(**data)

    def quote(self, price, timestamp, now=None):
        price = positive(price)
        timestamp = datetime.fromisoformat(timestamp)
        if timestamp.tzinfo is None:
            raise ValueError("Quote timestamp requires timezone")
        age = ((now or datetime.now(timezone.utc)) - timestamp).total_seconds()
        if age < 0 or age > self.max_quote_age_seconds:
            raise ValueError("Quote is stale or in the future; no fill simulated")
        return price

    def fill(self, price, side):
        direction = 1 if side == "BUY" else -1
        return price * (1 + direction * self.slippage_bps / 10000)

    def entry(self, price, qty, stop, day_pnl, cash, entry_fee=None, exit_fee=None):
        qty, price, stop = quantity(qty), positive(price), positive(stop)
        if stop >= price:
            raise ValueError("Long position stop must be below the entry price")
        if day_pnl <= -self.daily_loss_limit:
            raise ValueError("Daily loss limit reached; new entries blocked")
        entry_fee = self.fee_per_order if entry_fee is None else money(entry_fee)
        exit_fee = self.fee_per_order if exit_fee is None else money(exit_fee)
        cost = price * qty + entry_fee
        if price * qty > self.max_position_value:
            raise ValueError("Maximum position value exceeded")
        if (
            price - self.fill(stop, "SELL")
        ) * qty + entry_fee + exit_fee > self.max_trade_loss:
            raise ValueError(
                "Planned loss exceeds per-trade limit (gaps may still exceed it)"
            )
        if cost > cash:
            raise ValueError("Insufficient paper cash")

    def exit_reason(self, position, price):
        if price <= money(position["stop"]):
            return "stop_loss"
        # A trailing threshold is configured at entry and cannot be loosened by AI.
        trail = position["trailing_pct"]
        if trail is not None and price <= money(position["high"]) * (
            1 - money(trail) / 100
        ):
            return "trailing_stop"
        return None
