"""Continuous local-paper protection from an externally refreshed JSON quote feed."""

import hashlib
import json
import time
import math
from pathlib import Path


def monitor_cycle(broker, feed_path):
    events, errors = [], []
    try:
        feed = json.loads(Path(feed_path).read_text(encoding="utf-8"))
        if not isinstance(feed, dict):
            raise ValueError("Feed must be an object mapping symbols to quotes")
    except (OSError, ValueError) as exc:
        broker.pause(True)
        return {
            "events": [],
            "errors": [f"Quote feed unavailable: {type(exc).__name__}"],
            "entries_paused": True,
        }
    for position in broker.status()["positions"]:
        symbol = position["symbol"]
        try:
            quote = feed[symbol]
            # Validate before deduplication: an old, previously processed quote is still stale.
            broker.limits.quote(quote["price"], quote["timestamp"])
            # Quote identity must not depend on last_ts, which changes after a successful tick.
            payload = json.dumps(
                [symbol, position["position_id"], quote["price"], quote["timestamp"]],
                sort_keys=True,
            )
            key = "monitor:" + hashlib.sha256(payload.encode()).hexdigest()
            events.append(broker.tick(symbol, quote["price"], quote["timestamp"], key))
        except (KeyError, ValueError, TypeError) as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    if errors:
        broker.pause(True)
    return {
        "events": events,
        "errors": errors,
        "entries_paused": broker.status()["paused"],
        "mode": "local_paper",
        "note": "No broker orders; invalid feeds pause entries, never invent exit fills",
    }


def watch(broker, feed_path, interval=5, cycles=None, emit=print, source="file"):
    if source not in ("file", "yahoo"):
        raise ValueError("Unsupported quote source")
    if source == "yahoo" and interval < 30:
        raise ValueError("Yahoo polling requires an interval of at least 30 seconds")
    if (
        not math.isfinite(interval)
        or interval < 1
        or (cycles is not None and (type(cycles) is not int or cycles < 1))
    ):
        raise ValueError(
            "Interval and cycles must be positive (interval at least one second)"
        )
    from .health import heartbeat

    count = 0
    try:
        while cycles is None or count < cycles:
            heartbeat(broker.db, "collecting", {})
            collection_errors = []
            if source == "yahoo":
                from .market import collect, write_feed

                symbols = [p["symbol"] for p in broker.status()["positions"]]
                quotes, collection_errors = collect(symbols)
                try:
                    write_feed(feed_path, quotes)
                except OSError as exc:
                    broker.pause(True)
                    heartbeat(
                        broker.db, "degraded", {"reason": "Cannot save quote feed"}
                    )
                    emit(
                        json.dumps(
                            {
                                "events": [],
                                "errors": ["Cannot save quote feed"],
                                "error_type": type(exc).__name__,
                                "entries_paused": True,
                            }
                        )
                    )
                    count += 1
                    if cycles is None or count < cycles:
                        time.sleep(interval)
                    continue
            result = monitor_cycle(broker, feed_path)
            if collection_errors:
                result["collection_errors"] = collection_errors
            heartbeat(
                broker.db,
                "degraded" if result.get("errors") or collection_errors else "healthy",
                {"errors": result.get("errors", [])},
            )
            emit(json.dumps(result))
            count += 1
            if cycles is None or count < cycles:
                time.sleep(interval)
    except KeyboardInterrupt:
        heartbeat(broker.db, "stopped", {})
        return {
            "manager": "Paper monitoring stopped. No further automatic protection checks run."
        }
    heartbeat(broker.db, "stopped", {})
    return {"manager": "Paper monitoring completed", "cycles": count}
