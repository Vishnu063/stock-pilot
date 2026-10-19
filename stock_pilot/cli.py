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
    broker = PaperBroker(":memory:",limits)
    now = datetime.now(timezone.utc).isoformat()
    buy = broker.buy("DEMO",10,"100",now,"95","demo-entry", "3")
    hold = broker.tick("DEMO","105",now,"demo-rise")
    sell = broker.tick("DEMO","101",now,"demo-exit")
    return {"manager":"Offline synthetic demonstration, not market research", "roles":ROLES,
            "events":[buy,hold,sell],"portfolio":broker.status()}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stock Pilot Manager — research and local paper trading")
    parser.add_argument("--db", default="paper.db")
    parser.add_argument("--limits",default="examples/limits.json")
    sub = parser.add_subparsers(dest="command", required=True)
    for cmd in ("demo","team","status","pause","resume","openalgo-check"):
        sub.add_parser(cmd)
    r = sub.add_parser("chat")
    r.add_argument("message", nargs="?")
    r.add_argument("--reports-dir", default="reports")
    r = sub.add_parser("compare")
    r.add_argument("reports", nargs="+")
    r.add_argument("--date", required=True)
    r.add_argument("--output", default="reports/comparison.json")
    r = sub.add_parser("watch")
    r.add_argument("--feed", required=True)
    r.add_argument("--interval", type=float, default=5)
    r.add_argument("--cycles", type=int)
    r = sub.add_parser("research")
    r.add_argument("symbol")
    r.add_argument("--date", required=True, help="YYYY-MM-DD analysis date")
    r.add_argument("--config",default="examples/research.ollama.json")
    r.add_argument("--output",default="reports/research.json")
    for cmd in ("paper-buy","paper-tick"):
        p=sub.add_parser(cmd)
        p.add_argument("symbol")
        p.add_argument("--price",required=True)
        p.add_argument("--timestamp",required=True,help="Quote time in ISO 8601 with timezone")
        p.add_argument("--request-id",required=True)
        if cmd == "paper-buy":
            p.add_argument("--quantity",type=int,required=True)
            p.add_argument("--stop",required=True)
            p.add_argument("--trailing-pct")
    r=sub.add_parser("report")
    r.add_argument("csv")
    r.add_argument("--output",default="reports/performance.html")
    args=parser.parse_args(argv)
    try:
        if args.command == "demo":
            result=demo()
        elif args.command == "team":
            result=ROLES
        elif args.command == "openalgo-check":
            from .integrations import openalgo_status
            result=openalgo_status()
        elif args.command == "report":
            from .integrations import performance_report
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            result=performance_report(args.csv,args.output)
        else:
            with open(args.limits) as f:
                limits=Limits.load(json.load(f))
            broker=PaperBroker(args.db,limits)
            if args.command == "chat":
                from .manager import Manager
                manager = Manager(broker, args.reports_dir)
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
                    result = {"manager": "Chat closed; any separate watcher keeps running."}
            elif args.command == "compare":
                from .manager import compare
                result = compare(args.reports, args.date, broker)
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
            elif args.command == "watch":
                from .monitor import watch
                result = watch(broker, args.feed, args.interval, args.cycles)
            elif args.command == "status":
                result=broker.status()
            elif args.command in ("pause","resume"):
                result=broker.pause(args.command == "pause")
            elif args.command == "paper-buy":
                result=broker.buy(args.symbol,args.quantity,args.price,args.timestamp,args.stop,args.request_id,args.trailing_pct)
            elif args.command == "paper-tick":
                result=broker.tick(args.symbol,args.price,args.timestamp,args.request_id)
            else:
                result=research(args.symbol,args.date,args.config)
                result["investment_agent"]=investment_review(result,broker.status(),limits)
                Path(args.output).parent.mkdir(parents=True,exist_ok=True)
                Path(args.output).write_text(json.dumps(result,indent=2),encoding="utf-8")
        print(json.dumps(result,indent=2))
        return 0
    except Exception as exc:
        # Avoid printing HTTP bodies, which may contain credentials.
        print(f"Manager stopped: {type(exc).__name__}: check configuration, data and service availability.",file=sys.stderr)
        if isinstance(exc,(ValueError, FileNotFoundError, ModuleNotFoundError)):
            print(str(exc),file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
