"""Historical data diagnostics; declarations are not vendor authentication."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def inspect_dataset(path, bars, digest):
    """Read an optional <csv>.metadata.json, bound to the exact CSV bytes."""
    issues = []
    for previous, current in zip(bars, bars[1:]):
        change = abs(current["open"] / previous["close"] - 1)
        if change > 0.25:
            issues.append({"code": "LARGE_OVERNIGHT_MOVE", "date": current["date"].isoformat()})
    zero_volume = [b["date"].isoformat() for b in bars if b["volume"] == 0]
    if zero_volume:
        issues.append({"code": "ZERO_VOLUME", "dates": zero_volume})
    metadata_path = Path(str(path) + ".metadata.json")
    metadata = None
    if not metadata_path.exists():
        issues.append({"code": "MISSING_METADATA"})
    else:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
            raise ValueError("Unsupported historical data metadata")
        if metadata.get("dataset_sha256") != digest:
            raise ValueError("Historical metadata does not match CSV checksum")
        source = urlsplit(metadata.get("source_url", ""))
        if source.scheme != "https" or not source.hostname or source.username or source.password:
            raise ValueError("Historical source must be an HTTPS URL without credentials")
        captured = datetime.fromisoformat(metadata["captured_at"])
        if captured.tzinfo is None or captured > datetime.now(timezone.utc):
            raise ValueError("Historical capture time must be timezone-aware and not future")
        if not bars or captured.date() < bars[-1]["date"]:
            raise ValueError("Historical capture precedes dataset end")
        if not metadata.get("symbol") or metadata.get("currency") != "INR":
            raise ValueError("Historical metadata requires a symbol and INR currency")
        # Adjusted bars cannot be treated as raw cash fills; actions need a ledger model.
        if metadata.get("price_basis") != "raw" or metadata.get("corporate_actions") != []:
            issues.append({"code": "UNSUPPORTED_ADJUSTMENTS_OR_ACTIONS"})
        if metadata.get("corporate_actions_reviewed") is not True:
            issues.append({"code": "ACTIONS_NOT_REVIEWED"})
        sessions = metadata.get("expected_sessions")
        if not isinstance(sessions, list) or not sessions:
            issues.append({"code": "MISSING_SESSION_CALENDAR"})
        else:
            expected = [date.fromisoformat(s) for s in sessions]
            if expected != sorted(set(expected)):
                raise ValueError("Expected sessions must be unique and increasing")
            actual = {b["date"] for b in bars}
            missing = sorted(set(expected) - actual)
            unexpected = sorted(actual - set(expected))
            if missing:
                issues.append({"code": "MISSING_SESSIONS", "dates": [d.isoformat() for d in missing]})
            if unexpected:
                issues.append({"code": "UNEXPECTED_SESSIONS", "dates": [d.isoformat() for d in unexpected]})
    return {
        "status": "NEEDS_REVIEW" if issues else "DECLARED_CHECKS_PASSED",
        "dataset_sha256": digest,
        "metadata_present": metadata is not None,
        "symbol": metadata.get("symbol") if metadata else None,
        "issues": issues,
        "execution_allowed": False,
        "limitations": [
            "Metadata and sessions are operator declarations, not authenticated exchange records",
            "Large moves are warnings, not proof of a split or bad data",
            "No split, dividend, delisting or survivorship correction is performed",
            "Passing these checks does not validate financial claims or establish profitability",
        ],
    }
