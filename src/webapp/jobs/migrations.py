"""Transactional upgrades for durable Job metadata and event history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..redaction import safe_payload
from .errors import JobStateError


SCHEMA_VERSION = 3


def migrate_job_store(connection: sqlite3.Connection, job_root: Path) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise JobStateError("The Job database was created by a newer server version.")
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(jobs)")}
    if "revision" not in columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_events (
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (job_id, sequence)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS job_file_references (
            file_id TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES jobs(job_id),
            PRIMARY KEY (file_id, job_id)
        )
        """
    )
    if current < 3:
        for row in connection.execute("SELECT job_id, input_manifest_sha256 FROM jobs").fetchall():
            manifest_path = job_root / str(row[0]) / "input.json"
            if manifest_path.is_file():
                content = manifest_path.read_bytes()
                if hashlib.sha256(content).hexdigest() == row[1]:
                    manifest = json.loads(content)
                    for item in manifest.get("input", {}).get("files", []):
                        if isinstance(item, dict) and item.get("file_id"):
                            connection.execute("INSERT OR IGNORE INTO job_file_references VALUES (?, ?)", (item["file_id"], row[0]))
            path = job_root / str(row[0]) / "events.jsonl"
            if not path.is_file():
                continue
            for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("payload", {}), dict):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO job_events VALUES (?, ?, ?, ?, ?)",
                    (
                        row[0], sequence, str(event.get("event_type", "JOB_EVENT")),
                        str(event.get("timestamp", "")),
                        json.dumps(safe_payload(event.get("payload", {})), ensure_ascii=False, allow_nan=False),
                    ),
                )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.execute(
        "INSERT OR REPLACE INTO job_store_meta(key, value) VALUES('schema_version', ?)",
        (f"job_store_v{SCHEMA_VERSION}",),
    )
