"""Small guided console over existing workflows. No live mode or order entry UI."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from .paper import PaperBroker
from .risk import Limits

DEMO_LIMITS = {
    "max_position_value": "10000",
    "max_trade_loss": "200",
    "daily_loss_limit": "500",
    "max_quote_age_seconds": 60,
    "slippage_bps": "10",
    "fee_per_order": "2",
}


def require_paper_mode():
    if os.environ.get("STOCK_PILOT_MODE", "paper").strip().lower() != "paper":
        raise ValueError(
            "Live mode is not available. Use STOCK_PILOT_MODE=paper. No live credentials or orders are used."
        )


def open_profile(home, db_path=None):
    require_paper_mode()
    root = Path(home) / "paper"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings = root / "settings.json"
    if not settings.exists():
        with open(settings, "x", encoding="utf-8") as f:
            json.dump(
                {
                    "mode": "paper",
                    "model": "qwen3:4b",
                    "limits": DEMO_LIMITS,
                    "personal_policy_reviewed": False,
                    "costs_file": None,
                    "instruments_file": None,
                    "warning": "Demonstration limits, not personal risk settings",
                },
                f,
                indent=2,
            )
    config = json.loads(settings.read_text())
    if config.get("mode") != "paper":
        raise ValueError("Only paper profiles are supported")
    path = Path(db_path) if db_path else root / "paper.db"
    if db_path and not path.exists():
        raise ValueError("The selected existing database does not exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    new_account = not path.exists()
    costs = None
    if config.get("costs_file"):
        from .costs import CostSchedule

        costs = CostSchedule(json.loads((root / config["costs_file"]).read_text()))
    instruments = (
        json.loads((root / config["instruments_file"]).read_text())
        if config.get("instruments_file")
        else None
    )
    broker = PaperBroker(
        path,
        Limits.load(config["limits"]),
        cost_schedule=costs,
        instruments=instruments,
    )
    if new_account:
        broker.pause(True)
    os.chmod(path, 0o600)
    return broker, root, path, config


def portfolio_text(status):
    entry = (
        "LOCKED"
        if status.get("entry_lock")
        else "PAUSED"
        if status["paused"]
        else "UNPAUSED (paper only)"
    )
    rows = [
        f"New entries: {entry}",
        f"Paper cash: {status['cash']} INR | Equity: {status['equity']} INR",
        f"Open positions: {len(status['positions'])} | Marked drawdown: {float(status['drawdown_pct']):.2f}%",
    ]
    if status.get("entry_lock"):
        rows.append("Block reason: " + status["entry_lock"])
    for p in status["positions"]:
        rows.append(
            f"  {p['symbol']}: {p['quantity']} shares | last {p['last']} | stop {p['stop']}"
        )
    rows.append("Values reflect supplied paper quotes, not verified broker holdings.")
    return "\n".join(rows)


def setup_text(result):
    modules = result["optional_packages"]
    ollama = result["local_ollama"]
    target = "qwen3:4b"
    lines = [
        "SETUP CHECK — paper only",
        "Core demo: available (Python " + result["python"] + ")",
        "AI research package: "
        + ("installed" if modules["tradingagents"] else "not installed"),
        "Market-data package: "
        + ("installed" if modules["yfinance"] else "not installed"),
        "Ollama: "
        + ("reachable" if ollama["reachable"] else "not running or unreachable"),
        "Qwen model: "
        + ("installed" if target in ollama["models"] else "not detected"),
        "Market prices: not verified | Live trading: unavailable",
    ]
    if not modules["tradingagents"] or not modules["yfinance"]:
        lines.extend(
            [
                "To enable research/data after trying the offline demo:",
                '  python -m pip install -e ".[research,market]"',
            ]
        )
    if target not in ollama["models"]:
        lines.extend(
            [
                "With Ollama installed and running on your server:",
                "  ollama pull qwen3:4b",
            ]
        )
    lines.append("Installed packages alone do not establish data or model quality.")
    return "\n".join(lines)


def explain_reply(reply):
    if "portfolio" in reply:
        return portfolio_text(reply["portfolio"])
    if "report" in reply:
        report = reply["report"]
        reports = report.get("reports", {})
        return (
            f"{report.get('symbol', 'Unknown')} | {report.get('as_of', 'Date missing')} | {report.get('rating', 'Review')}\n"
            + str(reports.get("final_trade_decision", "No saved explanation"))
        )
    if "manager" in reply:
        return str(reply["manager"])
    if "paused" in reply:
        return "New entries are " + (
            "paused." if reply["paused"] else "unpaused in paper mode."
        )
    if "agents" in reply:
        return "\n".join(k.title() + ": " + v for k, v in reply["agents"].items())
    if "paper_closed_trades" in reply:
        return f"Closed paper trades: {reply['paper_closed_trades']} | Net realized P&L: {reply['paper_net_realized_pnl']} INR\nPaper results do not establish future returns."
    if "reports" in reply:
        return "\n".join(reply["reports"]) or "No saved reports yet."
    if "agency_runs" in reply:
        return (
            "\n".join(r["run_id"] + ": " + r["status"] for r in reply["agency_runs"])
            or "No agency jobs yet."
        )
    return "Request processed. See advanced commands for full details."


def run_menu(broker, root, db_path, config, ask=input, say=print):
    while True:
        state = broker.status()
        say("\nSTOCK PILOT — PAPER ONLY")
        say(
            "Entries: "
            + (
                "LOCKED"
                if state.get("entry_lock")
                else "PAUSED"
                if state["paused"]
                else "UNPAUSED"
            )
            + " | No live broker connected"
        )
        if not config.get("personal_policy_reviewed"):
            say("Demonstration limits — personal risk settings have not been reviewed.")
        say(
            "1 Setup check\n2 Try offline agency demo\n3 Talk to Manager\n4 Review portfolio\n5 Safety and backups\n6 Advanced workflows\n0 Exit"
        )
        try:
            choice = ask("Choose: ").strip()
            if choice == "0":
                return 0
            if choice == "1":
                from .doctor import diagnose
                from .health import check

                say(setup_text(diagnose()))
                say("Monitor: " + check(db_path)["message"])
            elif choice == "2":
                from .agency import demo

                result = demo()
                say("OFFLINE DEMO — synthetic research and quotes")
                for role in result["role_outputs"]:
                    say("  " + role.title() + ": completed")
                say("Manager decision: " + result["manager"]["decision"])
                say(
                    "No trade is expected without reviewed sources, costs and policy. Your paper account was not changed."
                )
            elif choice == "3":
                from .manager import Manager
                from .doctor import diagnose

                health = diagnose()
                model = config.get("model", "qwen3:4b")
                enabled = (
                    health["local_ollama"]["reachable"]
                    and model in health["local_ollama"]["models"]
                )
                manager = Manager(broker, root / "reports", model if enabled else None)
                say(
                    "Manager ready"
                    + (
                        " with local AI."
                        if enabled
                        else " for portfolio, pause, resume and saved-report requests. Local AI is unavailable."
                    )
                )
                say("Type help for requests, or back to return.")
                while True:
                    message = ask("You: ").strip()
                    if message.lower() in ("back", "exit", "quit"):
                        break
                    say(explain_reply(manager.reply(message)))
            elif choice == "4":
                say(portfolio_text(broker.status()))
            elif choice == "5":
                safety_menu(broker, root, ask, say)
            elif choice == "6":
                advanced_menu(broker, root, db_path, config, ask, say)
            else:
                say("Choose one of the listed numbers.")
        except (EOFError, KeyboardInterrupt):
            say(
                "\nConsole closed. Any separate monitor/watchdog processes are unchanged."
            )
            return 0
        except Exception as exc:
            say(
                "Could not complete that action: "
                + (
                    str(exc)
                    if isinstance(exc, (ValueError, FileNotFoundError, FileExistsError))
                    else type(exc).__name__
                )
            )
            say("The menu is still available. Review setup or retry with valid inputs.")


def safety_menu(broker, root, ask, say):
    say(
        "1 Pause entries\n2 Resume paper entries\n3 Emergency entry block\n4 Review and clear emergency block\n5 Create verified database backup\n6 Restore backup to a NEW locked copy\n0 Back"
    )
    choice = ask("Safety: ").strip()
    if choice == "1":
        broker.pause(True)
        say(
            "New entries paused. Protection still requires a running monitor and valid prices."
        )
    elif choice == "2":
        broker.pause(False)
        say("Paper entries unpaused. No live orders are enabled.")
    elif choice == "3":
        reason = ask("Reason for blocking new purchases: ").strip()
        broker.emergency_block(reason)
        say("New entries locked. Existing protective checks have not been disabled.")
    elif choice == "4":
        reason = ask("What did you review before clearing the block? ").strip()
        broker.clear_entry_block(reason)
        say("Block cleared. Entries remain paused until you explicitly resume.")
    elif choice == "5":
        from .storage import backup, default_backup_path

        result = backup(broker, default_backup_path(root / "backups"))
        say("Database backup verified: " + result["backup"])
        say(result["scope"])
    elif choice == "6":
        from .storage import restore

        source = ask("Backup .db path: ").strip()
        output = (
            root
            / "recoveries"
            / (
                "recovered-"
                + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                + ".db"
            )
        )
        result = restore(source, output)
        say("Recovered copy verified and entry-locked: " + result["restored"])
        say(
            "The running database was not replaced. To review it later: python3 start.py --db "
            + str(output)
        )
    elif choice != "0":
        say("Choose one of the listed numbers.")


def advanced_menu(broker, root, db_path, config, ask, say):
    say(
        "1 Research a stock\n2 Run existing agency job\n3 Evaluate local Qwen\n4 Check a market quote\n5 Show monitor/watchdog commands\n0 Back"
    )
    choice = ask("Advanced: ").strip()
    if choice == "1":
        research_prompt(root, config, ask, say)
    elif choice == "2":
        from .agency import run

        job_path = Path(ask("Job JSON path: ").strip())
        job = json.loads(job_path.read_text())
        run_id = ask("Run ID (reuse it to resume unchanged work): ").strip()
        result = run(broker, job, run_id, root / "reports" / "agency")
        say("Agency: " + result["status"])
        if result["status"] == "completed":
            say("Manager decision: " + result["manager"]["decision"])
            for reason in result["manager"]["reasons"]:
                say("  " + reason)
        else:
            say(
                "Stopped at "
                + str(result.get("completed_steps"))
                + " | "
                + result["error_type"]
            )
        say(
            "The guided profile uses demonstration limits until you review its configuration. No orders were placed."
        )
    elif choice == "3":
        from .model_eval import evaluate

        result = evaluate(config.get("model", "qwen3:4b"))
        out = root / "reports" / "model-evaluation.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))
        say(
            f"Model check: {result['status']} | {result['passed']}/{result['total']} synthetic tasks passed"
        )
        say("This does not establish investment skill. Full result: " + str(out))
    elif choice == "4":
        from .market import collect

        symbol = ask("NSE/BSE symbol, e.g. RELIANCE.NS: ").strip().upper()
        quotes, errors = collect([symbol])
        if errors:
            say(
                "No usable quote. Check the market package, connection and symbol. Entries should remain paused."
            )
        else:
            quote = quotes[symbol]
            say(
                symbol
                + ": "
                + quote["price"]
                + " INR | Source market time: "
                + quote["timestamp"]
            )
            try:
                broker.limits.quote(quote["price"], quote["timestamp"])
                say(
                    "Quote meets the current age check; it is still public paper-testing data."
                )
            except ValueError:
                say(
                    "Quote is stale or invalid for current protection. Closed markets or delayed data may cause this."
                )
    elif choice == "5":
        say(
            "Run these separately so the console does not claim a background process is active:"
        )
        say(
            "  python -m stock_pilot.cli --db "
            + str(db_path)
            + " watch --source yahoo --interval 30"
        )
        say(
            "  python -m stock_pilot.cli --db "
            + str(db_path)
            + " watchdog --alerts "
            + str(root / "alerts.jsonl")
        )
        say(
            "The watchdog produces local console/file alerts. Neither process can report a whole-host outage from that same host."
        )
    elif choice != "0":
        say("Choose one of the listed numbers.")


def research_prompt(root, config, ask, say):
    from .doctor import diagnose

    ready = diagnose()
    model = config.get("model", "qwen3:4b")
    if (
        not ready["optional_packages"]["tradingagents"]
        or not ready["local_ollama"]["reachable"]
        or model not in ready["local_ollama"]["models"]
    ):
        say(
            "Research needs the research package, running Ollama and the configured Qwen model."
        )
        say(setup_text(ready))
        return
    symbol = ask("Stock symbol, e.g. TCS or TCS.NS: ").strip().upper()
    if "." not in symbol:
        symbol += ".NS"
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.&_-]{0,30}\.(NS|BO)", symbol):
        raise ValueError("Use a valid NSE (.NS) or BSE (.BO) symbol")
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    as_of = ask("Analysis date [" + today + "]: ").strip() or today
    from .agents import research

    config_path = root / "research-config.json"
    # No API keys are needed or copied. Keep the local model on localhost.
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "llm_provider": "ollama",
                    "backend_url": "http://localhost:11434/v1",
                    "quick_think_llm": model,
                    "deep_think_llm": model,
                    "max_debate_rounds": 1,
                    "max_risk_discuss_rounds": 1,
                    "max_tool_rounds": 5,
                },
                indent=2,
            )
        )
    say(
        "Researching "
        + symbol
        + ". CPU inference may take time; no order will be placed."
    )
    report = research(symbol, as_of, config_path)
    # Source snapshots and a reviewed proposal are still needed for eligibility.
    path = root / "reports" / (symbol + "-" + report["as_of"] + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    say("Research saved: " + str(path))
    say(
        "Opinion: "
        + str(report.get("rating", "REVIEW"))
        + " | Evidence still needs review. No trade was placed."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Guided Stock Pilot paper console")
    parser.add_argument("--home", default="data")
    parser.add_argument("--db", help="Explicit existing paper/recovered database")
    args = parser.parse_args(argv)
    broker = None
    try:
        broker, root, path, config = open_profile(args.home, args.db)
        return run_menu(broker, root, path, config)
    except (ValueError, OSError) as exc:
        print("Startup stopped: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if broker is not None:
            broker.db.close()


if __name__ == "__main__":
    raise SystemExit(main())
