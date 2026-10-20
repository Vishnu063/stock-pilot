"""SQLite-consistent local backups and restores to a NEW, paused database."""

import hashlib
from contextlib import closing
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .journal import initialize, append, verify


def inspect(db):
    db.row_factory = sqlite3.Row
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("Database integrity check failed")
    required = {"account", "positions", "events"}
    present = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not required <= present:
        raise ValueError("Not a Stock Pilot paper database")
    if "journal" in present and not verify(db)["valid"]:
        raise ValueError("Journal integrity check failed")


def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    return path


def backup(broker, output):
    output = Path(output)
    manifest = Path(str(output) + ".json")
    if manifest.exists():
        raise ValueError("Backup manifest already exists; choose a new name")
    exclusive(output)
    try:
        with closing(sqlite3.connect(output)) as destination:
            broker.db.backup(destination, pages=128, sleep=0.01)
            inspect(destination)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        metadata = {
            "format": "stock-pilot-paper-backup-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sha256": digest,
            "mode": "paper",
            "database": output.name,
            "scope": "Database only. Research files, evidence snapshots, settings and model weights are not included.",
        }
        with open(manifest, "x", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
        os.chmod(manifest, 0o600)
        return {
            "backup": str(output),
            "manifest": str(manifest),
            "verified": True,
            "scope": metadata["scope"],
        }
    except Exception:
        output.unlink(missing_ok=True)
        raise


def restore(source, output):
    source, output = Path(source), Path(output)
    metadata = json.loads(Path(str(source) + ".json").read_text())
    if (
        metadata.get("format") != "stock-pilot-paper-backup-v1"
        or metadata.get("mode") != "paper"
    ):
        raise ValueError("Only verified Stock Pilot paper backups can be restored")
    if hashlib.sha256(source.read_bytes()).hexdigest() != metadata.get("sha256"):
        raise ValueError("Backup checksum changed; restore refused")
    # Never replace the running database, even if its name is supplied accidentally.
    exclusive(output)
    try:
        with (
            closing(
                sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as origin,
            closing(sqlite3.connect(output)) as destination,
        ):
            inspect(origin)
            origin.backup(destination, pages=128, sleep=0.01)
            inspect(destination)
            if "entry_lock" not in {
                r[1] for r in destination.execute("PRAGMA table_info(account)")
            }:
                destination.execute("ALTER TABLE account ADD COLUMN entry_lock TEXT")
            destination.execute(
                "UPDATE account SET paused=1,entry_lock='Restored account needs review and reconciliation' WHERE id=1"
            )
            initialize(destination)
            append(
                destination,
                "RESTORED",
                {"backup_sha256": metadata["sha256"], "entries_locked": True},
            )
            destination.commit()
            inspect(destination)
        return {
            "restored": str(output),
            "verified": True,
            "entries_locked": True,
            "next": "Review this recovered copy and reconcile its state before clearing the entry block. The original database was not replaced.",
        }
    except Exception:
        output.unlink(missing_ok=True)
        raise


def default_backup_path(directory):
    return Path(directory) / (
        datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid4().hex[:6]
        + ".db"
    )
