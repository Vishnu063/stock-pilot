"""Local append-only API with a hash-linked audit trail, not tamper-proof storage."""

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4
from .risk import money


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS journal(
        sequence INTEGER PRIMARY KEY, entry_id TEXT UNIQUE NOT NULL,
        timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
        previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS observations(
        decision_id TEXT PRIMARY KEY, observation_entry_id TEXT NOT NULL)""")


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(entry_id, timestamp, kind, payload, previous):
    return hashlib.sha256(
        canonical([entry_id, timestamp, kind, payload, previous]).encode()
    ).hexdigest()


def append(db, kind, payload):
    # Caller owns the transaction, so order and journal records commit together.
    last = db.execute(
        "SELECT entry_hash FROM journal ORDER BY sequence DESC LIMIT 1"
    ).fetchone()
    previous = last[0] if last else "0" * 64
    entry_id = str(uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    raw = canonical(payload)
    entry_hash = digest(entry_id, timestamp, kind, raw, previous)
    db.execute(
        "INSERT INTO journal(entry_id,timestamp,kind,payload,previous_hash,entry_hash) VALUES(?,?,?,?,?,?)",
        (entry_id, timestamp, kind, raw, previous, entry_hash),
    )
    return entry_id


def entries(db):
    return [
        {**dict(row), "payload": json.loads(row["payload"])}
        for row in db.execute("SELECT * FROM journal ORDER BY sequence")
    ]


def verify(db):
    previous = "0" * 64
    count = 0
    for row in db.execute("SELECT * FROM journal ORDER BY sequence"):
        expected = digest(
            row["entry_id"], row["timestamp"], row["kind"], row["payload"], previous
        )
        if row["previous_hash"] != previous or row["entry_hash"] != expected:
            return {"valid": False, "broken_sequence": row["sequence"]}
        previous = row["entry_hash"]
        count += 1
    return {
        "valid": True,
        "entries": count,
        "head_hash": previous,
        "limitation": "A local administrator could rewrite the entire chain; retain a separate trusted copy of the head hash",
    }


def record_assessment(broker, report, proposal, decision):
    with broker.transaction():
        return append(
            broker.db,
            "ASSESSMENT",
            {"research": report, "proposal": proposal, "decision": decision},
        )


def observe(broker, decision_id, price, timestamp, reason):
    from .evidence import aware
    from .risk import positive

    when = aware(timestamp)
    now = datetime.now(timezone.utc)
    if when > now or not isinstance(reason, str) or not reason.strip():
        raise ValueError("Observation needs a past/current timestamp and explanation")
    with broker.transaction():
        if broker.db.execute(
            "SELECT 1 FROM observations WHERE decision_id=?", (decision_id,)
        ).fetchone():
            raise ValueError("An observation is already recorded for this decision")
        row = broker.db.execute(
            "SELECT payload,timestamp FROM journal WHERE entry_id=? AND kind='ASSESSMENT'",
            (decision_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown assessment ID")
        saved = json.loads(row["payload"])
        proposal = saved["proposal"]
        entered = aware(proposal["quote"]["timestamp"])
        if when < entered or when < aware(row["timestamp"]):
            raise ValueError("Observation predates decision or source quote")
        initial = positive(proposal["quote"]["price"])
        final = positive(price)
        payload = {
            "decision_id": decision_id,
            "price": str(final),
            "observed_at": timestamp,
            "price_return": str((final - initial) / initial),
            "reason": reason,
            "days_observed": (when - entered).total_seconds() / 86400,
            "planned_holding_days": proposal.get("holding_days"),
            "classification": "counterfactual"
            if saved["decision"]["decision"] == "NO_TRADE"
            else "paper_followup",
            "realized_pnl_claim": False,
            "note": "Supplied follow-up price, not a broker-confirmed fill or independently verified outcome",
        }
        entry_id = append(broker.db, "OBSERVATION", payload)
        broker.db.execute(
            "INSERT INTO observations VALUES(?,?)", (decision_id, entry_id)
        )
        return {"entry_id": entry_id, **payload}


def summary(db):
    rows = entries(db)
    sells = [r["payload"]["result"] for r in rows if r["kind"] == "SELL"]
    pnl = sum((money(r["net_trade_pnl"]) for r in sells), money("0"))
    reasons = {}
    for trade in sells:
        reason = trade.get("reason", "unknown")
        reasons[reason] = reasons.get(reason, 0) + 1
    wins = sum(money(r["net_trade_pnl"]) > 0 for r in sells)
    assessments = [r for r in rows if r["kind"] == "ASSESSMENT"]
    return {
        "paper_closed_trades": len(sells),
        "paper_net_realized_pnl": str(pnl),
        "paper_winning_trades": wins,
        "paper_losing_trades": sum(money(r["net_trade_pnl"]) < 0 for r in sells),
        "paper_exit_reasons": reasons,
        "recorded_assessments": len(assessments),
        "no_trade_decisions": sum(
            r["payload"]["decision"]["decision"] == "NO_TRADE" for r in assessments
        ),
        "backtest_runs": sum(r["kind"] == "BACKTEST" for r in rows),
        "observations": sum(r["kind"] == "OBSERVATION" for r in rows),
        "note": "Local paper fills only; excludes open P&L. Observations are not counted as realized profits.",
    }
