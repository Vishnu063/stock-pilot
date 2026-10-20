"""Manager command interface. Offline demo requires no API keys or packages."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from .agents import ROLES, research, investment_review
from .paper import PaperBroker
from .risk import Limits


def demo():
    limits = Limits("10000", "200", "500", fee_per_order="2")
    broker = PaperBroker(":memory:", limits)
    now = datetime.now(timezone.utc).isoformat()
    buy = broker.buy("DEMO", 10, "100", now, "95", "demo-entry", "3")
    hold = broker.tick("DEMO", "105", now, "demo-rise")
    sell = broker.tick("DEMO", "101", now, "demo-exit")
    return {
        "manager": "Offline synthetic demonstration, not market research",
        "roles": ROLES,
        "events": [buy, hold, sell],
        "portfolio": broker.status(),
    }


def main(argv=None):
    from .console import require_paper_mode

    try:
        require_paper_mode()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        from .console import main as guided_main

        return guided_main([])
    parser = argparse.ArgumentParser(
        description="Stock Pilot Manager — research and local paper trading"
    )
    parser.add_argument("--db", default="paper.db")
    parser.add_argument("--instruments", help="Reviewed sector/risk-group mapping JSON")
    parser.add_argument("--costs", help="Reviewed itemized cost schedule JSON")
    parser.add_argument("--limits", default="examples/limits.json")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in (
        "demo",
        "team",
        "status",
        "pause",
        "resume",
        "openalgo-check",
        "agency-demo",
    ):
        sub.add_parser(cmd)
    r = sub.add_parser("menu")
    r.add_argument("--home", default="data")
    r = sub.add_parser("backup")
    r.add_argument("--output", required=True)
    r = sub.add_parser("restore")
    r.add_argument("backup")
    r.add_argument("--output", required=True)
    r = sub.add_parser("emergency-stop")
    r.add_argument("--reason", required=True)
    r = sub.add_parser("unlock-entries")
    r.add_argument("--reason", required=True)
    r = sub.add_parser("watchdog")
    r.add_argument("--alerts", default="reports/alerts.jsonl")
    r.add_argument("--interval", type=float, default=5)
    r.add_argument("--cycles", type=int)
    r.add_argument("--max-heartbeat-age", type=int, default=90)
    r = sub.add_parser("agency")
    r.add_argument("job")
    r.add_argument("--run-id", required=True)
    r.add_argument("--output-dir", default="reports/agency")
    r.add_argument("--lease-seconds", type=int, default=3600)
    r = sub.add_parser("agency-status")
    r.add_argument("run_id", nargs="?")
    r = sub.add_parser("evaluate-model")
    r.add_argument("--model", default="qwen3:4b")
    r.add_argument("--output", default="reports/model-evaluation.json")
    r = sub.add_parser("backtest-suite")
    r.add_argument("manifest")
    r.add_argument("--output", default="reports/evaluation-suite.json")
    r = sub.add_parser("reconcile")
    r.add_argument("expected")
    r.add_argument("observed")
    r.add_argument("--max-age-seconds", type=int, default=60)
    r.add_argument("--pause-on-mismatch", action="store_true")
    r = sub.add_parser("thesis")
    thesis_sub = r.add_subparsers(dest="thesis_command", required=True)
    t = thesis_sub.add_parser("add")
    t.add_argument("definition")
    t.add_argument("--id", required=True)
    thesis_sub.add_parser("list")
    t = thesis_sub.add_parser("review")
    t.add_argument("thesis_id")
    t.add_argument("facts")
    r = sub.add_parser("chat")
    r.add_argument("message", nargs="?")
    r.add_argument("--reports-dir", default="reports")
    r.add_argument(
        "--model",
        help="Enable read-only explanations with an installed local Ollama model",
    )
    r = sub.add_parser("compare")
    r.add_argument("reports", nargs="+")
    r.add_argument("--date", required=True)
    r.add_argument("--output", default="reports/comparison.json")
    r = sub.add_parser("watch")
    r.add_argument("--feed", default="reports/quotes.json")
    r.add_argument("--source", choices=["file", "yahoo"], default="file")
    r.add_argument("--interval", type=float, default=5)
    r.add_argument("--cycles", type=int)
    r = sub.add_parser("collect")
    r.add_argument("symbols", nargs="+")
    r.add_argument("--output", default="reports/quotes.json")
    r = sub.add_parser("attach-evidence")
    r.add_argument("report")
    r.add_argument("manifest")
    r.add_argument("--output", required=True)
    r = sub.add_parser("data-check")
    r.add_argument("csv")
    r = sub.add_parser("backtest")
    r.add_argument("csv")
    r.add_argument("--split-date", required=True)
    r.add_argument(
        "--benchmark",
        help="Optional OHLC reference series CSV with matching holdout dates",
    )
    r.add_argument("--output", default="reports/backtest.json")
    r = sub.add_parser("assess")
    r.add_argument("report")
    r.add_argument("proposal")
    r = sub.add_parser("journal")
    r.add_argument("--verify", action="store_true")
    r.add_argument("--summary", action="store_true")
    r = sub.add_parser("observe")
    r.add_argument("decision_id")
    r.add_argument("--price", required=True)
    r.add_argument("--timestamp", required=True)
    r.add_argument("--reason", required=True)
    r = sub.add_parser("doctor")
    r = sub.add_parser("research")
    r.add_argument("symbol")
    r.add_argument("--date", required=True, help="YYYY-MM-DD analysis date")
    r.add_argument("--config", default="examples/research.ollama.json")
    r.add_argument("--output", default="reports/research.json")
    for cmd in ("paper-buy", "paper-tick"):
        p = sub.add_parser(cmd)
        p.add_argument("symbol")
        p.add_argument("--price", required=True)
        p.add_argument(
            "--timestamp", required=True, help="Quote time in ISO 8601 with timezone"
        )
        p.add_argument("--request-id", required=True)
        if cmd == "paper-buy":
            p.add_argument("--quantity", type=int, required=True)
            p.add_argument("--stop", required=True)
            p.add_argument("--trailing-pct")
    r = sub.add_parser("report")
    r.add_argument("csv")
    r.add_argument("--output", default="reports/performance.html")
    args = parser.parse_args(arguments)
    try:
        if args.command == "menu":
            from .console import main as guided_main

            return guided_main(["--home", args.home])
        elif args.command == "restore":
            from .storage import restore

            result = restore(args.backup, args.output)
        elif args.command == "watchdog":
            from .health import supervise

            result = supervise(
                args.db, args.alerts, args.interval, args.cycles, args.max_heartbeat_age
            )
            if (
                args.cycles is not None
                and result.get("last_health", {}).get("status") == "CRITICAL"
            ):
                print(json.dumps(result, indent=2))
                return 1
        elif args.command == "data-check":
            from .backtest import load_bars
            from .data_quality import inspect_dataset

            bars, digest = load_bars(args.csv)
            result = inspect_dataset(args.csv, bars, digest)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "DECLARED_CHECKS_PASSED" else 1
        elif args.command == "demo":
            result = demo()
        elif args.command == "agency-demo":
            from .agency import demo as agency_demo

            result = agency_demo()
        elif args.command == "evaluate-model":
            from .model_eval import evaluate as evaluate_model

            result = evaluate_model(args.model)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] == result["total"] else 1
        elif args.command == "team":
            result = ROLES
        elif args.command == "attach-evidence":
            from .evidence import attach

            result = attach(args.report, args.manifest, args.output)
        elif args.command == "doctor":
            from .doctor import diagnose

            result = diagnose()
        elif args.command == "collect":
            from .market import collect, write_feed

            quotes, errors = collect(args.symbols)
            write_feed(args.output, quotes)
            result = {
                "quotes": quotes,
                "errors": errors,
                "output": args.output,
                "mode": "paper_data_only",
            }
            if not quotes:
                print(json.dumps(result, indent=2))
                return 1
        elif args.command == "openalgo-check":
            from .integrations import openalgo_status

            result = openalgo_status()
        elif args.command == "report":
            from .integrations import performance_report

            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            result = performance_report(args.csv, args.output)
        else:
            with open(args.limits) as f:
                limits = Limits.load(json.load(f))
            schedule = None
            if args.costs:
                from .costs import CostSchedule

                schedule = CostSchedule(json.loads(Path(args.costs).read_text()))
            instruments = (
                json.loads(Path(args.instruments).read_text())
                if args.instruments
                else None
            )
            if (
                args.command in ("backup", "emergency-stop", "unlock-entries")
                and not Path(args.db).is_file()
            ):
                raise ValueError(
                    "Select an existing paper account with --db; no account was created"
                )
            broker = PaperBroker(
                args.db, limits, cost_schedule=schedule, instruments=instruments
            )
            if args.command == "backup":
                from .storage import backup

                result = backup(broker, args.output)
            elif args.command == "emergency-stop":
                result = broker.emergency_block(args.reason)
            elif args.command == "unlock-entries":
                result = broker.clear_entry_block(args.reason)
            elif args.command == "agency":
                from .agency import run

                job = json.loads(Path(args.job).read_text())
                result = run(
                    broker,
                    job,
                    args.run_id,
                    args.output_dir,
                    lease_seconds=args.lease_seconds,
                )
                if result["status"] == "failed":
                    print(json.dumps(result, indent=2))
                    return 1
            elif args.command == "agency-status":
                from .agency import status as agency_status

                result = agency_status(broker, args.run_id)
            elif args.command == "thesis":
                from .thesis import create, list_theses, review

                if args.thesis_command == "add":
                    result = create(
                        broker, args.id, json.loads(Path(args.definition).read_text())
                    )
                elif args.thesis_command == "review":
                    result = review(
                        broker, args.thesis_id, json.loads(Path(args.facts).read_text())
                    )
                else:
                    result = list_theses(broker)
            elif args.command == "backtest-suite":
                if schedule is None:
                    raise ValueError(
                        "Evaluation suites require an explicit historical cost schedule"
                    )
                from .evaluation_suite import evaluate_suite
                from .journal import append, evaluated_datasets

                result = evaluate_suite(
                    json.loads(Path(args.manifest).read_text()), schedule
                )
                history = evaluated_datasets(broker.db)
                for job in result["jobs"]:
                    if job["status"] == "completed":
                        job["result"]["previous_runs_on_same_dataset"] = history.get(
                            job["result"]["dataset_sha256"], 0
                        )
                with broker.transaction():
                    append(broker.db, "BACKTEST_SUITE", result)
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(result, indent=2))
                if result["failed_jobs"]:
                    print(json.dumps(result, indent=2))
                    return 1
            elif args.command == "reconcile":
                from .reconciliation import FileSnapshotSource, reconcile
                from .journal import append

                expected, expected_hash = FileSnapshotSource(args.expected).read()
                observed, observed_hash = FileSnapshotSource(args.observed).read()
                result = reconcile(expected, observed, args.max_age_seconds)
                result.update(
                    expected_sha256=expected_hash, observed_sha256=observed_hash
                )
                with broker.transaction():
                    append(broker.db, "RECONCILIATION", result)
                if args.pause_on_mismatch and result["entries_should_be_blocked"]:
                    broker.pause(True)
                if result["entries_should_be_blocked"]:
                    print(json.dumps(result, indent=2))
                    return 1
            elif args.command == "backtest":
                if schedule is None:
                    raise ValueError(
                        "Backtesting requires an explicit itemized historical cost schedule"
                    )
                from .backtest import evaluate

                result = evaluate(
                    args.csv, schedule, args.split_date, benchmark_path=args.benchmark
                )
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(result, indent=2))
                from .journal import append, evaluated_datasets

                previous_runs = evaluated_datasets(broker.db).get(
                    result["dataset_sha256"], 0
                )
                result["previous_runs_on_same_dataset"] = previous_runs
                if previous_runs:
                    result["limitations"].append(
                        "This dataset has been evaluated before; do not treat it as a fresh unseen holdout"
                    )
                Path(args.output).write_text(json.dumps(result, indent=2))
                with broker.transaction():
                    append(broker.db, "BACKTEST", result)
            elif args.command == "assess":
                from .decision import assess
                from .journal import record_assessment

                report = json.loads(Path(args.report).read_text())
                proposal = json.loads(Path(args.proposal).read_text())
                result = assess(report, proposal, broker)
                result["decision_id"] = record_assessment(
                    broker, report, proposal, result
                )
            elif args.command == "journal":
                from .journal import entries, verify, summary

                result = (
                    verify(broker.db)
                    if args.verify
                    else summary(broker.db)
                    if args.summary
                    else entries(broker.db)
                )
            elif args.command == "observe":
                from .journal import observe

                result = observe(
                    broker, args.decision_id, args.price, args.timestamp, args.reason
                )
            elif args.command == "chat":
                from .manager import Manager

                manager = Manager(broker, args.reports_dir, args.model)
                if args.message:
                    result = manager.reply(args.message)
                else:
                    print("Manager ready. Type help or exit.")
                    while True:
                        try:
                            message = input("You: ")
                        except (EOFError, KeyboardInterrupt):
                            break
                        if message.strip().lower() in ("exit", "quit"):
                            break
                        print(json.dumps(manager.reply(message), indent=2))
                    result = {
                        "manager": "Chat closed; any separate watcher keeps running."
                    }
            elif args.command == "compare":
                from .manager import compare

                result = compare(args.reports, args.date, broker)
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(
                    json.dumps(result, indent=2), encoding="utf-8"
                )
            elif args.command == "watch":
                from .monitor import watch

                result = watch(
                    broker, args.feed, args.interval, args.cycles, source=args.source
                )
            elif args.command == "status":
                result = broker.status()
            elif args.command in ("pause", "resume"):
                result = broker.pause(args.command == "pause")
            elif args.command == "paper-buy":
                result = broker.buy(
                    args.symbol,
                    args.quantity,
                    args.price,
                    args.timestamp,
                    args.stop,
                    args.request_id,
                    args.trailing_pct,
                )
            elif args.command == "paper-tick":
                result = broker.tick(
                    args.symbol, args.price, args.timestamp, args.request_id
                )
            else:
                result = research(args.symbol, args.date, args.config)
                result["investment_agent"] = investment_review(
                    result, broker.status(), limits
                )
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(
                    json.dumps(result, indent=2), encoding="utf-8"
                )
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        # Avoid printing HTTP bodies, which may contain credentials.
        print(
            f"Manager stopped: {type(exc).__name__}: check configuration, data and service availability.",
            file=sys.stderr,
        )
        if isinstance(exc, (ValueError, FileNotFoundError, ModuleNotFoundError)):
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
