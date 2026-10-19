"""Conversational command router and transparent comparison of research opinions."""

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from .agents import ROLES, investment_review

RATINGS = {"Buy": 4, "Overweight": 3, "Hold": 2, "Underweight": 1, "Sell": 0}


def evidence_check(report, as_of, now=None):
    """Check report structure and citation presence, never claim source verification."""
    now = now or datetime.now(timezone.utc)
    problems = []
    if date.fromisoformat(as_of) > now.astimezone(ZoneInfo("Asia/Kolkata")).date():
        raise ValueError("Comparison date cannot be in the future")
    if report.get("as_of") != as_of:
        problems.append("Analysis date differs from requested comparison date")
    try:
        generated = datetime.fromisoformat(report["generated_at"])
        age = (now - generated).total_seconds()
        if generated.tzinfo is None or age < 0 or age > 86400:
            problems.append(
                "Report generation timestamp is invalid or older than 24 hours"
            )
    except (KeyError, ValueError, TypeError):
        problems.append("Missing or invalid generation timestamp")
    reports = report.get("reports", {})
    if not isinstance(reports, dict):
        reports = {}
    sources = {}
    for key in (
        "market_report",
        "news_report",
        "fundamentals_report",
        "final_trade_decision",
    ):
        text = reports.get(key, "")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"Missing {key}")
            text = ""
        urls = sorted(set(re.findall(r"https?://[^\s<>\[\]()]+", text)))
        urls = [url for url in urls if urlsplit(url).hostname]
        sources[key] = urls
        if key in ("news_report", "fundamentals_report") and not urls:
            problems.append(f"No source URLs in {key}")
    from .evidence import check

    problems.extend(check(report, as_of))
    if report.get("rating") not in RATINGS:
        problems.append("Unrecognized analyst rating")
    return {
        "problems": problems,
        "source_urls": sources,
        "source_verification": "URLs detected only; article contents and publication times are unverified",
    }


def compare(paths, as_of, broker):
    if date.fromisoformat(as_of) > datetime.now(ZoneInfo("Asia/Kolkata")).date():
        raise ValueError("Comparison date cannot be in the future")
    candidates, rejected, seen = [], [], set()
    status = broker.status()
    for path in paths:
        try:
            report = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise ValueError("Report must be a JSON object")
            symbol = report.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise ValueError("Missing symbol")
            if symbol in seen:
                raise ValueError("Duplicate stock report")
            seen.add(symbol)
            evidence = evidence_check(report, as_of)
            review = investment_review(report, status, broker.limits)
            objections = evidence["problems"] + review["protection_objections"]
            saved_reports = (
                report.get("reports") if isinstance(report.get("reports"), dict) else {}
            )
            row = {
                "symbol": symbol,
                "rating": report.get("rating"),
                "source_file": str(path),
                "evidence": evidence,
                "protection_review": review,
                "research_summary": saved_reports.get("final_trade_decision", ""),
            }
            if objections:
                row["reasons"] = objections
                rejected.append(row)
            else:
                row["rating_order"] = RATINGS[report["rating"]]
                candidates.append(row)
        except (OSError, ValueError, TypeError) as exc:
            rejected.append({"source_file": str(path), "reasons": [str(exc)]})
    candidates.sort(key=lambda row: (-row["rating_order"], row["symbol"]))
    for i, row in enumerate(candidates, 1):
        row["rank"] = i
    return {
        "manager": "Research opinion comparison, not a buy instruction",
        "as_of": as_of,
        "ranking_method": "Upstream ordinal rating; alphabetical tie break; no predicted returns or calibrated confidence",
        "candidates": candidates,
        "needs_review": rejected,
        "execution_allowed": False,
        "limitations": [
            "Sources and publication times not independently verified",
            "Investment suitability and timeframe not assessed",
            "Historical analysis is not a current trading signal",
        ],
    }


class Manager:
    def __init__(self, broker, reports_dir="reports", model=None):
        self.broker, self.reports_dir = broker, Path(reports_dir)
        self.model, self.history = model, []

    def reply(self, message):
        text = " ".join(message.lower().strip().split()).rstrip(".!?")
        if text in (
            "status",
            "portfolio",
            "review my portfolio",
            "show my portfolio",
            "how are we doing",
        ):
            return {
                "manager": "Here is your local paper portfolio. Prices reflect supplied ticks.",
                "portfolio": self.broker.status(),
            }
        if text in ("pause", "pause trading", "stop trading"):
            return self.broker.pause(True)
        if text in ("resume", "resume trading"):
            return self.broker.pause(False)
        if text in ("performance", "show performance", "show results"):
            from .journal import summary

            return summary(self.broker.db)
        if text in ("team", "show agents", "who does what"):
            return {"agents": ROLES}
        if text in ("reports", "show reports", "show research"):
            return {"reports": sorted(str(p) for p in self.reports_dir.glob("*.json"))}
        if text in ("help", "what can you do"):
            return {
                "manager": "Ask: review my portfolio; pause trading; resume trading; show agents; show reports; why SYMBOL.",
                "note": "This is a deterministic conversational router, not an unrestricted LLM chatbot. Use research and compare commands for analyses.",
            }
        why = re.fullmatch(r"why ([a-z0-9.&^_-]{1,40})", text)
        if why:
            symbol = why.group(1).upper()
            matches = []
            for path in self.reports_dir.glob("*.json"):
                try:
                    report = json.loads(path.read_text())
                    if isinstance(report, dict) and report.get("symbol") == symbol:
                        matches.append(report)
                except (OSError, ValueError):
                    continue
            if matches:
                report = max(matches, key=lambda r: str(r.get("generated_at", "")))
                return {
                    "manager": "Latest saved research; verify its date and sources before acting.",
                    "report": report,
                }
            return {
                "manager": f"No saved research for {symbol}. Run the research command first."
            }
        if self.model:
            from .chat import explain

            saved = []
            for path in sorted(
                self.reports_dir.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:3]:
                try:
                    saved.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            try:
                answer = explain(
                    message, self.broker.status(), saved, self.model, self.history
                )
                self.history.extend(
                    [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": answer["manager"]},
                    ]
                )
                self.history = self.history[-6:]
                return answer
            except Exception as exc:
                return {
                    "manager": "Local AI is unavailable. Explicit portfolio, pause and resume commands still work.",
                    "error_type": type(exc).__name__,
                    "execution_allowed": False,
                }
        return {
            "manager": "I have not changed anything. Type help for supported requests.",
            "execution_allowed": False,
        }
