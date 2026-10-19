"""Read-only reconciliation contract for normalized broker snapshots.

Broker-specific adapters and authentication are intentionally absent until a
broker is selected. A matching exported snapshot is not trading authorization.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .evidence import aware
from .risk import money, positive


class FileSnapshotSource:
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        raw = self.path.read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()


def whole(value):
    number = money(value)
    if number < 0 or number != number.to_integral_value():
        raise ValueError("Quantity must be a nonnegative whole number")
    return int(number)


def instrument(value):
    if (
        not isinstance(value, str)
        or len(value.split(":")) != 3
        or not all(value.split(":"))
    ):
        raise ValueError("Instrument must be EXCHANGE:SYMBOL:PRODUCT")
    return value


def positions(snapshot, issues, label):
    result = {}
    rows = snapshot.get("positions")
    if not isinstance(rows, list):
        issues.append({"code": "MISSING_POSITIONS", "source": label})
        return result
    for row in rows:
        try:
            key = instrument(row["instrument"])
            qty = whole(row["quantity"])
            if key in result:
                raise ValueError("Duplicate instrument row")
            result[key] = qty
        except (ValueError, TypeError, KeyError):
            issues.append({"code": "INVALID_POSITION", "source": label})
    return result


def orders(snapshot, issues, label):
    result = {}
    broker_ids = set()
    rows = snapshot.get("orders")
    if not isinstance(rows, list):
        issues.append({"code": "MISSING_ORDERS", "source": label})
        return result
    for row in rows:
        try:
            client = row["client_id"]
            if not isinstance(client, str) or not client:
                raise ValueError("Client ID required")
            if client in result:
                issues.append(
                    {
                        "code": "DUPLICATE_CLIENT_ID",
                        "client_id": client,
                        "source": label,
                    }
                )
                continue
            key = instrument(row["instrument"])
            qty = whole(row["quantity"])
            filled = whole(row.get("filled_quantity", 0))
            if qty <= 0 or filled > qty or row["side"] not in ("BUY", "SELL"):
                raise ValueError("Invalid quantities or side")
            status = row["status"]
            allowed = (
                "OPEN",
                "PARTIALLY_FILLED",
                "FILLED",
                "CANCELLED",
                "REJECTED",
                "EXPIRED",
                "UNKNOWN",
            )
            if label == "expected":
                allowed += ("PENDING_SUBMIT",)
            if status not in allowed or status == "UNKNOWN":
                issues.append(
                    {
                        "code": "UNKNOWN_ORDER_STATUS",
                        "client_id": client,
                        "source": label,
                    }
                )
            if (
                (status == "FILLED" and filled != qty)
                or (status == "PARTIALLY_FILLED" and not 0 < filled < qty)
                or (status == "OPEN" and filled != 0)
            ):
                issues.append(
                    {
                        "code": "INCONSISTENT_FILL_STATUS",
                        "client_id": client,
                        "source": label,
                    }
                )
            broker_id = row.get("broker_order_id")
            if label == "observed":
                if not isinstance(broker_id, str) or not broker_id:
                    raise ValueError("Broker order ID required")
                if broker_id in broker_ids:
                    issues.append(
                        {
                            "code": "DUPLICATE_BROKER_ORDER_ID",
                            "broker_order_id": broker_id,
                        }
                    )
                broker_ids.add(broker_id)
            result[client] = {
                **row,
                "instrument": key,
                "quantity": qty,
                "filled_quantity": filled,
            }
        except (ValueError, TypeError, KeyError):
            issues.append({"code": "INVALID_ORDER", "source": label})
    return result


def reconcile(expected, observed, max_age_seconds=60, now=None):
    now = now or datetime.now(timezone.utc)
    issues = []
    if not isinstance(expected, dict) or not isinstance(observed, dict):
        raise ValueError("Snapshots must be objects")
    if type(max_age_seconds) is not int or max_age_seconds <= 0:
        raise ValueError("Snapshot age limit must be positive")
    try:
        stamp = aware(observed["captured_at"])
        age = (now - stamp).total_seconds()
        if age < 0 or age > max_age_seconds:
            issues.append({"code": "STALE_OR_FUTURE_BROKER_SNAPSHOT"})
    except (KeyError, ValueError, TypeError):
        issues.append({"code": "INVALID_SNAPSHOT_TIMESTAMP"})
    if not isinstance(observed.get("source"), str) or not observed["source"].strip():
        issues.append({"code": "MISSING_SNAPSHOT_SOURCE"})
    wanted = positions(expected, issues, "expected")
    actual = positions(observed, issues, "observed")
    expected_orders = orders(expected, issues, "expected")
    actual_orders = orders(observed, issues, "observed")
    for key in sorted(set(wanted) | set(actual)):
        if wanted.get(key, 0) != actual.get(key, 0):
            issues.append(
                {
                    "code": "POSITION_MISMATCH",
                    "instrument": key,
                    "expected": wanted.get(key, 0),
                    "observed": actual.get(key, 0),
                }
            )
    for client, order in expected_orders.items():
        found = actual_orders.get(client)
        if found is None:
            issues.append(
                {
                    "code": "UNCONFIRMED_ORDER",
                    "client_id": client,
                    "action": "Check broker history; do not blindly resubmit",
                }
            )
            continue
        if any(order[k] != found[k] for k in ("instrument", "side", "quantity")):
            issues.append({"code": "ORDER_IDENTITY_MISMATCH", "client_id": client})
        if order.get("broker_order_id") and order["broker_order_id"] != found.get(
            "broker_order_id"
        ):
            issues.append({"code": "BROKER_ORDER_ID_MISMATCH", "client_id": client})
        if found["status"] in ("REJECTED", "CANCELLED", "EXPIRED"):
            issues.append(
                {
                    "code": "ORDER_NOT_ACTIVE_OR_FILLED",
                    "client_id": client,
                    "status": found["status"],
                }
            )
    for client in set(actual_orders) - set(expected_orders):
        issues.append({"code": "UNEXPECTED_ORDER", "client_id": client})
    for client, order in actual_orders.items():
        if (
            order["side"] == "BUY"
            and order["status"] in ("OPEN", "PARTIALLY_FILLED")
            and order["filled_quantity"] < order["quantity"]
        ):
            issues.append(
                {
                    "code": "ENTRY_ORDER_REMAINS_OPEN",
                    "client_id": client,
                    "remaining_quantity": order["quantity"] - order["filled_quantity"],
                }
            )
    if expected.get("account_id") is not None and expected.get(
        "account_id"
    ) != observed.get("account_id"):
        issues.append({"code": "ACCOUNT_ID_MISMATCH"})
    coverage = {}
    for client, order in actual_orders.items():
        if order.get("purpose") == "PROTECTION" and order["status"] in (
            "OPEN",
            "PARTIALLY_FILLED",
        ):
            if order["side"] != "SELL" or order.get("order_type") != "STOP":
                issues.append({"code": "INVALID_PROTECTIVE_ORDER", "client_id": client})
                continue
            try:
                positive(order["trigger_price"])
            except (KeyError, ValueError, TypeError):
                issues.append({"code": "INVALID_STOP_TRIGGER", "client_id": client})
                continue
            key = order["instrument"]
            coverage[key] = (
                coverage.get(key, 0) + order["quantity"] - order["filled_quantity"]
            )
    if expected.get("require_protection", True) is not False:
        for key, qty in actual.items():
            covered = coverage.get(key, 0)
            if covered < qty:
                issues.append(
                    {
                        "code": "UNPROTECTED_REMAINDER",
                        "instrument": key,
                        "quantity": qty - covered,
                    }
                )
            if covered > qty:
                issues.append(
                    {
                        "code": "OVERSELL_RISK",
                        "instrument": key,
                        "excess": covered - qty,
                    }
                )
    for key, covered in coverage.items():
        if key not in actual or actual.get(key) == 0:
            issues.append(
                {
                    "code": "ORPHAN_PROTECTIVE_ORDER",
                    "instrument": key,
                    "quantity": covered,
                }
            )
    return {
        "status": "MATCHED" if not issues else "REVIEW_REQUIRED",
        "issues": issues,
        "entries_should_be_blocked": bool(issues),
        "protective_coverage": coverage,
        "execution_allowed": False,
        "read_only": True,
        "limitations": [
            "Normalized snapshots are caller supplied, not authenticated broker responses",
            "Long-only whole-share positions and simple stop orders; OCO and broker-specific semantics are not modeled",
            "Snapshot exports may omit history; actual adapter must supply a complete, consistent view",
        ],
    }
