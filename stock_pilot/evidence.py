"""Local source snapshots with hashes and publication-time checks.

A hash proves snapshot consistency, not publisher authenticity or factual correctness.
No URLs from model output are fetched automatically.
"""

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

PRIMARY_DOMAINS = ("nseindia.com", "bseindia.com", "sebi.gov.in")


def aware(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Evidence timestamps require a timezone")
    return result


def cutoff(as_of):
    return datetime.combine(
        date.fromisoformat(as_of), time.max, ZoneInfo("Asia/Kolkata")
    )


def primary_host(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Source URL must be HTTPS without embedded credentials")
    host = parsed.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in PRIMARY_DOMAINS)


def attach(report_path, manifest_path, output):
    report_path, manifest_path, output = map(Path, (report_path, manifest_path, output))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(manifest, list) or not manifest:
        raise ValueError("Expected a report object and nonempty list of source records")
    records = []
    for item in manifest:
        if not isinstance(item, dict) or item.get("category") not in (
            "news",
            "fundamentals",
        ):
            raise ValueError("Each source needs news or fundamentals category")
        if item.get("symbol") != report.get("symbol"):
            raise ValueError("Evidence symbol mismatch")
        published, captured = aware(item["published_at"]), aware(item["captured_at"])
        if (
            published > cutoff(report["as_of"])
            or published > captured
            or captured > datetime.now(timezone.utc)
        ):
            raise ValueError(
                "Invalid source publication/capture order or future evidence"
            )
        primary = primary_host(item["url"])
        snapshot = (manifest_path.parent / item["file"]).resolve()
        content = snapshot.read_bytes()
        if not content.strip():
            raise ValueError("Source snapshot is empty")
        digest = hashlib.sha256(content).hexdigest()
        destination = output.parent / "evidence" / (digest + ".snapshot")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        records.append(
            {
                k: item[k]
                for k in ("symbol", "url", "category", "published_at", "captured_at")
            }
        )
        records[-1].update(
            {
                "sha256": digest,
                "snapshot": str(destination.resolve()),
                "primary_domain": primary,
            }
        )
    report["evidence"] = records
    report["evidence_attached_at"] = datetime.now(timezone.utc).isoformat()
    report["execution_allowed"] = False
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return {
        "output": str(output),
        "source_count": len(records),
        "note": "Local provenance only; authenticity, completeness and factual accuracy are not independently verified",
    }


def check(report, as_of):
    errors, categories, primary_categories = [], set(), set()
    records = report.get("evidence")
    if not isinstance(records, list) or not records:
        return ["No structured source snapshots attached"]
    for record in records:
        try:
            if record.get("symbol") != report.get("symbol"):
                raise ValueError("Source belongs to a different stock")
            category = record["category"]
            if category not in ("news", "fundamentals"):
                raise ValueError("Unknown source category")
            published, captured = (
                aware(record["published_at"]),
                aware(record["captured_at"]),
            )
            if (
                published > cutoff(as_of)
                or published > captured
                or captured > datetime.now(timezone.utc)
            ):
                raise ValueError(
                    "Evidence has invalid or future publication/capture time"
                )
            digest = hashlib.sha256(Path(record["snapshot"]).read_bytes()).hexdigest()
            if digest != record["sha256"]:
                raise ValueError("Source snapshot changed after attachment")
            primary = primary_host(record["url"])
            import re

            text = report.get("reports", {}).get(category + "_report", "")
            cited = {
                url.rstrip(".,;")
                for url in re.findall(r"https?://[^\s<>\[\]()]+", text)
            }
            if record["url"] not in cited:
                raise ValueError(
                    "Snapshot URL is not cited in its corresponding research section"
                )
            categories.add(category)
            if primary:
                primary_categories.add(category)
        except (KeyError, ValueError, TypeError, OSError, AttributeError) as exc:
            errors.append(str(exc))
    if "news" not in categories:
        errors.append("Missing dated news evidence")
    if "fundamentals" not in primary_categories:
        errors.append("Missing primary-domain financial evidence")
    return errors
