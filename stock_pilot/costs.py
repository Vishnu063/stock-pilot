"""Configurable itemized costs. Rates come from a reviewed external schedule, not the LLM."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from .risk import money, positive, quantity


class CostSchedule:
    def __init__(self, config):
        self.config = config
        self.reviewed = config.get("reviewed") is True
        self.name = config["name"]
        self.start = date.fromisoformat(config["effective_from"])
        self.end = date.fromisoformat(config["effective_until"])
        if self.end < self.start:
            raise ValueError("Cost schedule validity is reversed")
        self.charges = config["charges"]
        if not isinstance(self.charges, list) or not self.charges:
            raise ValueError("Cost schedule needs itemized charges")
        names = set()
        for item in self.charges:
            if item["name"] in names:
                raise ValueError("Duplicate charge name")
            if item["name"] + "_gst" in names or (
                item["name"].endswith("_gst") and item["name"][:-4] in names
            ):
                raise ValueError("Charge name collides with generated GST item")
            names.add(item["name"])
            if item.get("side", "BOTH") not in ("BUY", "SELL", "BOTH"):
                raise ValueError("Charge side must be BUY, SELL or BOTH")
            for key in ("rate_bps", "fixed", "gst_pct"):
                if money(item.get(key, "0")) < 0:
                    raise ValueError("Negative cost rate")
            if item.get("cap") is not None:
                positive(item["cap"])
            positive(item.get("round_to", "0.01"))

    def calculate(self, price, qty, side, trade_date):
        if side not in ("BUY", "SELL"):
            raise ValueError("Invalid cost side")
        when = date.fromisoformat(trade_date)
        if not self.start <= when <= self.end:
            raise ValueError("Cost schedule is outside its effective dates")
        turnover = positive(price) * quantity(qty)
        breakdown = {}
        for item in self.charges:
            if item.get("side", "BOTH") not in ("BOTH", side):
                continue
            amount = turnover * money(item.get("rate_bps", "0")) / 10000 + money(
                item.get("fixed", "0")
            )
            if item.get("cap") is not None:
                amount = min(amount, money(item["cap"]))
            rounding = positive(item.get("round_to", "0.01"))
            amount = (amount / rounding).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            ) * rounding
            breakdown[item["name"]] = str(amount)
            gst = amount * money(item.get("gst_pct", "0")) / 100
            if gst:
                breakdown[item["name"] + "_gst"] = str(
                    gst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                )
        return {
            "schedule": self.name,
            "reviewed": self.reviewed,
            "side": side,
            "turnover": str(turnover),
            "items": breakdown,
            "total": str(sum(map(money, breakdown.values()), Decimal(0))),
        }
