"""SQLite state, stored outside the source tree."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artists (id INTEGER PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE, track_count INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS artist_matches (artist_id INTEGER PRIMARY KEY REFERENCES artists(id) ON DELETE CASCADE, provider_id TEXT, provider_name TEXT, checked_at TEXT, is_manual INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, metadata_json TEXT NOT NULL, indexed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, params_json TEXT NOT NULL, progress_json TEXT NOT NULL DEFAULT '{}', result_json TEXT, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, id);
PRAGMA user_version = 1;
"""

class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise RuntimeError(f"Unsupported database version: {version}")
            if version == 0:
                conn.executescript(SCHEMA)
                version = 1
            if version == 1:
                conn.executescript("CREATE TABLE catalog_cache (provider_id TEXT PRIMARY KEY, albums_json TEXT NOT NULL, fetched_at TEXT NOT NULL); PRAGMA user_version = 2;")
                version = 2
            if version == 2:
                conn.executescript("CREATE TABLE music_imports (path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, persistent_id TEXT, location TEXT); PRAGMA user_version = 3;")
        self.path.chmod(0o600)

    def status(self):
        with self.connect() as conn:
            return {"artists": conn.execute("SELECT count(*) FROM artists").fetchone()[0],
                    "indexed_files": conn.execute("SELECT count(*) FROM files").fetchone()[0],
                    "jobs": conn.execute("SELECT count(*) FROM jobs").fetchone()[0]}

    def jobs(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT id, kind, status, progress_json, result_json, error, created_at, updated_at FROM jobs ORDER BY id DESC LIMIT 100").fetchall()
        return [{**{k: row[k] for k in ("id", "kind", "status", "error", "created_at", "updated_at")},
                 "progress": json.loads(row["progress_json"]),
                 "result": json.loads(row["result_json"]) if row["result_json"] else None} for row in rows]
