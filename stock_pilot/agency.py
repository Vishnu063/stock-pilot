"""Sequential, checkpointed research agency. No order-submission path exists.

Completed steps are reused. A crash inside a read/model task can repeat that task;
final assessment journaling and checkpointing commit together to avoid duplicates.
"""

import hashlib
import json
import re
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .agents import research
from .decision import assess
from .evidence import attach
from .journal import append, canonical


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agency_runs(
        run_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL,
        status TEXT NOT NULL, owner TEXT, lease_until REAL NOT NULL DEFAULT 0,
        error_type TEXT)""")


def fingerprint(job, broker):
    files = {}
    for key in (
        "saved_report",
        "research_config",
        "evidence_manifest",
        "expected_snapshot",
        "observed_snapshot",
    ):
        if job.get(key):
            path = Path(job[key])
            files[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    # If evidence is supplied via a manifest, freeze the local snapshot bytes too.
    if job.get("evidence_manifest"):
        manifest = Path(job["evidence_manifest"])
        for item in json.loads(manifest.read_text()):
            path = (manifest.parent / item["file"]).resolve()
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    from . import __version__
    config = {
        "engine_version": __version__,
        "job": job,
        "files": files,
        "limits": asdict(broker.limits),
        "costs": broker.cost_schedule.config if broker.cost_schedule else None,
        "instruments": broker.instruments,
    }
    raw = json.dumps(config, sort_keys=True, default=str, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def status(broker, run_id=None):
    initialize(broker.db)
    if run_id:
        row = broker.db.execute(
            "SELECT * FROM agency_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown agency run")
        return {**dict(row), "state": json.loads(row["state"])}
    return [
        {k: dict(r)[k] for k in ("run_id", "status", "error_type")}
        for r in broker.db.execute("SELECT * FROM agency_runs ORDER BY run_id")
    ]


def run(
    broker,
    job,
    run_id,
    output_dir="reports/agency",
    researcher=None,
    after_step=None,
    lease_seconds=3600,
):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id):
        raise ValueError(
            "Run ID must contain 1–64 letters, numbers, underscores or hyphens"
        )
    if not isinstance(job, dict) or not isinstance(job.get("proposal"), dict):
        raise ValueError("Agency job requires a proposal object")
    if job.get("symbol") != job["proposal"].get("symbol"):
        raise ValueError("Job and proposal symbols differ")
    if type(lease_seconds) is not int or lease_seconds < 60:
        raise ValueError("Lease must be at least 60 seconds")
    initialize(broker.db)
    signature = fingerprint(job, broker)
    owner = str(uuid4())
    with broker.transaction():
        row = broker.db.execute(
            "SELECT * FROM agency_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if row and row["fingerprint"] != signature:
            raise ValueError("Inputs or policy changed; use a new run ID")
        if row and row["status"] == "running" and row["lease_until"] > time.time():
            raise ValueError(
                "Run has an active lease; another worker may still be processing it"
            )
        state = json.loads(row["state"]) if row else {}
        broker.db.execute(
            """INSERT INTO agency_runs VALUES(?,?,?,?,?,?,NULL)
            ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, owner=excluded.owner,
            lease_until=excluded.lease_until,error_type=NULL""",
            (
                run_id,
                signature,
                canonical(state),
                "running",
                owner,
                time.time() + lease_seconds,
            ),
        )

    def save(step, value, journal_kind=None):
        if fingerprint(job,broker) != signature:
            raise ValueError("Job inputs or policy changed during processing")
        with broker.transaction():
            current = broker.db.execute(
                "SELECT owner,lease_until FROM agency_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if current["owner"] != owner or current["lease_until"] < time.time():
                raise ValueError(
                    "Run lease expired or ownership changed; result not committed"
                )
            if journal_kind:
                value["journal_id"] = append(
                    broker.db,
                    journal_kind,
                    {"run_id": run_id, "job": job, "result": value},
                )
            state[step] = value
            broker.db.execute(
                "UPDATE agency_runs SET state=?,lease_until=? WHERE run_id=? AND owner=?",
                (canonical(state), time.time() + lease_seconds, run_id, owner),
            )
        if after_step:
            after_step(step)

    try:
        work = Path(output_dir) / run_id
        work.mkdir(parents=True, exist_ok=True)
        if "research" not in state:
            if job.get("saved_report"):
                report = json.loads(Path(job["saved_report"]).read_text())
            else:
                report = (researcher or research)(
                    job["symbol"], job["as_of"], job["research_config"]
                )
            if (
                report.get("symbol") != job["symbol"]
                or report.get("as_of") != job["as_of"]
            ):
                raise ValueError(
                    "Research returned the wrong instrument or analysis date"
                )
            save("research", report)
        if "evidence" not in state:
            report = state["research"]
            if job.get("evidence_manifest"):
                source = work / "raw.json"
                source.write_text(json.dumps(report))
                destination = work / "evidenced.json"
                attach(source, job["evidence_manifest"], destination)
                report = json.loads(destination.read_text())
            save("evidence", report)
        if job.get("thesis") and "thesis" not in state:
            from .thesis import create

            if job["thesis"].get("symbol") != job["symbol"]:
                raise ValueError("Thesis and job symbols differ")
            save("thesis", create(broker, "agency:" + run_id, job["thesis"]))
        if bool(job.get("expected_snapshot")) != bool(job.get("observed_snapshot")):
            raise ValueError(
                "Both expected and observed broker snapshots are required together"
            )

        def current_reconciliation():
            if not job.get("observed_snapshot"):
                return {
                    "status": "NOT_CONFIGURED",
                    "issues": [],
                    "execution_allowed": False,
                }
            from .reconciliation import FileSnapshotSource, reconcile

            expected, _ = FileSnapshotSource(job["expected_snapshot"]).read()
            observed, _ = FileSnapshotSource(job["observed_snapshot"]).read()
            return reconcile(expected, observed)

        if "reconciliation" not in state:
            save("reconciliation", current_reconciliation())

        fresh_quote = None
        quote_failure = None
        quote_source = job.get("quote_source", "supplied")
        if quote_source not in ("supplied", "yahoo"):
            raise ValueError("Unsupported agency quote_source")
        if quote_source == "yahoo":
            from .market import yahoo_quote
            try:
                fresh_quote = yahoo_quote(job["symbol"])
            except Exception as exc:
                quote_failure = type(exc).__name__

        def current_assessment():
            proposal = dict(job["proposal"])
            if quote_source == "yahoo":
                # Never fall back to the job's old quote after a collection failure.
                proposal["quote"] = fresh_quote or {}
            result = assess(state["evidence"], proposal, broker)
            result["quote_used"] = proposal.get("quote")
            if quote_failure:
                result["decision"] = "NO_TRADE"
                result["reasons"].append("Fresh Yahoo quote unavailable: " + quote_failure)
            reconciled = current_reconciliation()
            if reconciled["status"] == "REVIEW_REQUIRED":
                result["decision"] = "NO_TRADE"
                result["reasons"].append("Broker reconciliation requires review")
            result["broker_reconciliation"] = reconciled
            return result

        if "protection" not in state:
            save("protection", current_assessment())
        if "investment" not in state:
            protection = state["protection"]
            bullish = state["research"].get("rating") in ("Buy", "Overweight")
            save(
                "investment",
                {
                    "research_rating": state["research"].get("rating"),
                    "decision": protection["decision"],
                    "risk_objections": protection["reasons"],
                    "disagreement": bullish and protection["decision"] == "NO_TRADE",
                    "resolution": "Protection objections take precedence; agent agreement is not evidence of profit",
                },
            )
        if "manager" not in state:
            save(
                "manager",
                {
                    "decision": state["protection"]["decision"],
                    "disagreements": [state["investment"]]
                    if state["investment"]["disagreement"]
                    else [],
                    "reasons": state["protection"]["reasons"],
                    "execution_allowed": False,
                    "assessment": state["protection"],
                },
                "AGENCY_DECISION",
            )
        with broker.transaction():
            broker.db.execute(
                "UPDATE agency_runs SET status='completed',owner=NULL,lease_until=0 WHERE run_id=? AND owner=?",
                (run_id, owner),
            )
        # Cached decisions are historical artifacts. Never reuse their eligibility blindly.
        current = current_assessment()
        current_investment = {**state["investment"], "decision":current["decision"],
                              "risk_objections":current["reasons"],
                              "disagreement":state["research"].get("rating") in ("Buy","Overweight") and current["decision"] == "NO_TRADE"}
        current_manager = {"decision":current["decision"], "reasons":current["reasons"],
                           "disagreements":[current_investment] if current_investment["disagreement"] else [],
                           "historical_journal_id":state["manager"].get("journal_id"),
                           "execution_allowed":False}
        return {
            "run_id": run_id,
            "status": "completed",
            "completed_steps": list(state),
            "role_outputs": {
                "strategy": {
                    "market_report": state["research"]
                    .get("reports", {})
                    .get("market_report"),
                    "trader_proposal": state["research"]
                    .get("reports", {})
                    .get("trader_investment_plan"),
                },
                "research": {
                    "news_report": state["research"]
                    .get("reports", {})
                    .get("news_report"),
                    "fundamentals_report": state["research"]
                    .get("reports", {})
                    .get("fundamentals_report"),
                },
                "protection": current,
                "investment": current_investment,
                "manager": current_manager,
            },
            "manager": current_manager,
            "historical_manager": state["manager"],
            "current_readiness": current,
            "execution_allowed": False,
            "note": "No paper or broker orders are placed by the agency coordinator",
        }
    except Exception as exc:
        with broker.transaction():
            broker.db.execute(
                "UPDATE agency_runs SET status='failed',owner=NULL,lease_until=0,error_type=? WHERE run_id=? AND owner=?",
                (type(exc).__name__, run_id, owner),
            )
        return {
            "run_id": run_id,
            "status": "failed",
            "completed_steps": list(state),
            "error_type": type(exc).__name__,
            "execution_allowed": False,
            "next": "Correct service availability and repeat the same immutable job/run ID; changed inputs require a new ID",
        }


def demo():
    """Offline coordination demonstration. All research and quotes are synthetic."""
    from datetime import datetime, timezone
    from tempfile import TemporaryDirectory
    from zoneinfo import ZoneInfo
    from .paper import PaperBroker
    from .risk import Limits

    now = datetime.now(timezone.utc)
    report = {
        "symbol": "DEMO.NS",
        "as_of": now.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat(),
        "generated_at": now.isoformat(),
        "rating": "Buy",
        "reports": {
            key: "Synthetic demonstration only; no verified market evidence."
            for key in (
                "market_report",
                "news_report",
                "fundamentals_report",
                "investment_plan",
                "trader_investment_plan",
                "final_trade_decision",
            )
        },
    }
    proposal = {
        "symbol": "DEMO.NS",
        "quantity": 1,
        "stop": "95",
        "target": "120",
        "holding_days": 30,
        "quote": {
            "price": "100",
            "timestamp": now.isoformat(),
            "currency": "INR",
            "source": "synthetic",
        },
        "average_daily_turnover": "10000000",
        "spread_bps": "5",
    }
    with TemporaryDirectory() as d:
        path = Path(d) / "research.json"
        path.write_text(json.dumps(report))
        broker = PaperBroker(":memory:", Limits("10000", "200", "500"))
        try:
            result = run(
                broker,
                {
                    "symbol": "DEMO.NS",
                    "as_of": report["as_of"],
                    "saved_report": str(path),
                    "proposal": proposal,
                },
                "offline-demo",
                d,
            )
        finally:
            broker.db.close()
    result["demonstration"] = (
        "Synthetic inputs; NO_TRADE is expected because evidence and reviewed policies are absent"
    )
    return result
