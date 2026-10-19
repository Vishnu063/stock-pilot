"""Preserve an investment thesis and evaluate explicit invalidation criteria."""

import json
from datetime import datetime, timezone
from uuid import uuid4
from .evidence import aware
from .journal import append, canonical
from .risk import money


def initialize(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS theses(thesis_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,definition TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS thesis_reviews(review_id TEXT PRIMARY KEY,thesis_id TEXT NOT NULL,reviewed_at TEXT NOT NULL,result TEXT NOT NULL)"
    )


def create(broker, thesis_id, definition):
    initialize(broker.db)
    if not isinstance(thesis_id, str) or not thesis_id.strip():
        raise ValueError("Thesis ID is required")
    if not isinstance(definition, dict) or not all(
        isinstance(definition.get(k), str) and definition[k].strip()
        for k in ("symbol", "rationale", "review_at")
    ):
        raise ValueError("Thesis needs symbol, rationale and review_at")
    if (
        type(definition.get("holding_days")) is not int
        or not 1 <= definition["holding_days"] <= 3650
    ):
        raise ValueError("Thesis holding_days must be a positive whole number")
    aware(definition["review_at"])
    if (
        type(definition.get("max_fact_age_days", 120)) is not int
        or definition.get("max_fact_age_days", 120) <= 0
    ):
        raise ValueError("max_fact_age_days must be a positive whole number")
    rules = definition.get("invalidation_rules")
    if not isinstance(rules, list) or not rules:
        raise ValueError("Specify explicit invalidation rules")
    for rule in rules:
        if (
            not isinstance(rule.get("metric"), str)
            or not rule["metric"].strip()
            or rule.get("operator") not in ("lt", "le", "gt", "ge")
        ):
            raise ValueError("Invalid thesis metric or operator")
        money(rule["threshold"])
    for event in definition.get("events", []):
        if not isinstance(event.get("name"), str) or not event["name"].strip():
            raise ValueError("Event name required")
        aware(event["at"])
    raw = canonical(definition)
    with broker.transaction():
        row = broker.db.execute(
            "SELECT definition FROM theses WHERE thesis_id=?", (thesis_id,)
        ).fetchone()
        if row:
            if row[0] != raw:
                raise ValueError(
                    "Thesis is immutable; create a new ID for revised rules"
                )
            return {"thesis_id": thesis_id, "created": False}
        broker.db.execute(
            "INSERT INTO theses VALUES(?,?,?)",
            (thesis_id, datetime.now(timezone.utc).isoformat(), raw),
        )
        append(
            broker.db,
            "THESIS_CREATED",
            {"thesis_id": thesis_id, "definition": definition},
        )
    return {"thesis_id": thesis_id, "created": True, "execution_allowed": False}


def list_theses(broker):
    initialize(broker.db)
    return [
        {
            "thesis_id": r["thesis_id"],
            "created_at": r["created_at"],
            "definition": json.loads(r["definition"]),
        }
        for r in broker.db.execute("SELECT * FROM theses ORDER BY created_at")
    ]


def review(broker, thesis_id, facts, now=None):
    initialize(broker.db)
    now = now or datetime.now(timezone.utc)
    row = broker.db.execute(
        "SELECT definition FROM theses WHERE thesis_id=?", (thesis_id,)
    ).fetchone()
    if row is None:
        raise ValueError("Unknown thesis ID")
    definition = json.loads(row[0])
    if facts.get("symbol") != definition["symbol"]:
        raise ValueError("Facts refer to a different stock")
    observed = aware(facts["observed_at"])
    if observed > now:
        raise ValueError("Facts cannot be observed in the future")
    if facts.get("source_reviewed") is not True:
        raise ValueError("Facts require an explicit source_reviewed declaration")
    max_age = definition.get("max_fact_age_days", 120)
    if type(max_age) is not int or max_age <= 0:
        raise ValueError("Thesis max_fact_age_days must be a positive whole number")
    metrics = facts.get("metrics", {})
    missing = []
    breaches = []
    if (now - observed).total_seconds() > max_age * 86400:
        missing.append("fresh_financial_observations")
    for rule in definition["invalidation_rules"]:
        metric = rule["metric"]
        if metric not in metrics:
            missing.append(metric)
            continue
        value, threshold = money(metrics[metric]), money(rule["threshold"])
        hit = {
            "lt": value < threshold,
            "le": value <= threshold,
            "gt": value > threshold,
            "ge": value >= threshold,
        }[rule["operator"]]
        if hit:
            breaches.append(rule)
    due = aware(definition["review_at"]) <= now
    upcoming = [
        e
        for e in definition.get("events", [])
        if 0 <= (aware(e["at"]) - now).total_seconds() <= 3 * 86400
    ]
    result = {
        "thesis_id": thesis_id,
        "symbol": definition["symbol"],
        "status": "THESIS_INVALIDATED"
        if breaches
        else "INSUFFICIENT_DATA"
        if missing
        else "REVIEW_DUE"
        if due
        else "THESIS_UNCHANGED",
        "breaches": breaches,
        "missing_metrics": missing,
        "review_due": due,
        "upcoming_events": upcoming,
        "facts": facts,
        "execution_allowed": False,
        "note": "Supplied financial observations are not independently verified. This review never submits an exit order.",
    }
    review_id = str(uuid4())
    with broker.transaction():
        broker.db.execute(
            "INSERT INTO thesis_reviews VALUES(?,?,?,?)",
            (review_id, thesis_id, now.isoformat(), canonical(result)),
        )
        append(broker.db, "THESIS_REVIEW", {"review_id": review_id, **result})
    return {"review_id": review_id, **result}
