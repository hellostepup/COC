"""SQLite storage. Every change is committed immediately, so progress survives restarts."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    player_tag TEXT DEFAULT '',
    town_hall INTEGER NOT NULL DEFAULT 1,
    focus TEXT DEFAULT '',
    objective TEXT NOT NULL DEFAULT 'balanced',
    priority_gold INTEGER NOT NULL DEFAULT 34,
    priority_elixir INTEGER NOT NULL DEFAULT 33,
    priority_dark INTEGER NOT NULL DEFAULT 33,
    min_gold INTEGER NOT NULL DEFAULT 0,
    min_elixir INTEGER NOT NULL DEFAULT 0,
    min_dark INTEGER NOT NULL DEFAULT 0,
    troop_composition TEXT DEFAULT '',
    defense_avoidance TEXT NOT NULL DEFAULT 'medium',
    gold INTEGER NOT NULL DEFAULT 0,
    elixir INTEGER NOT NULL DEFAULT 0,
    dark_elixir INTEGER NOT NULL DEFAULT 0,
    max_gold INTEGER NOT NULL DEFAULT 0,
    max_elixir INTEGER NOT NULL DEFAULT 0,
    max_dark INTEGER NOT NULL DEFAULT 0,
    builders_total INTEGER NOT NULL DEFAULT 5,
    builders_busy_untracked INTEGER NOT NULL DEFAULT 0,
    rotation_order INTEGER NOT NULL DEFAULT 0,
    fill_storage_when_done INTEGER NOT NULL DEFAULT 0,
    last_flags TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS upgrades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    building TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    current_level INTEGER NOT NULL DEFAULT 0,
    target_level INTEGER NOT NULL DEFAULT 1,
    cost_gold INTEGER NOT NULL DEFAULT 0,
    cost_elixir INTEGER NOT NULL DEFAULT 0,
    cost_dark INTEGER NOT NULL DEFAULT 0,
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    builders_required INTEGER NOT NULL DEFAULT 1,
    quantity INTEGER NOT NULL DEFAULT 1,
    done_count INTEGER NOT NULL DEFAULT 0,
    cost_either INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'planned',
    started_at TEXT,
    completes_at TEXT,
    completed_at TEXT,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered INTEGER NOT NULL DEFAULT 0,
    read INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    image_path TEXT,
    image_width INTEGER,
    image_height INTEGER,
    result_json TEXT NOT NULL DEFAULT '{}',
    corrected_json TEXT,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after the first release; added to existing databases on startup.
MIGRATIONS = {
    "accounts": {"fill_storage_when_done": "INTEGER NOT NULL DEFAULT 0"},
    "upgrades": {
        "quantity": "INTEGER NOT NULL DEFAULT 1",
        "done_count": "INTEGER NOT NULL DEFAULT 0",
        "cost_either": "INTEGER NOT NULL DEFAULT 0",
    },
}


def default_data_dir() -> str:
    base = os.environ.get("COC_MANAGER_DATA")
    if base:
        return base
    if os.name == "nt":
        root = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        root = os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(root, "COCManager")


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols.items():
                if name not in have:
                    self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self.tx() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def insert(self, table: str, data: Dict[str, Any]) -> int:
        cols = ", ".join(data.keys())
        marks = ", ".join("?" for _ in data)
        return self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))

    def update(self, table: str, row_id: int, data: Dict[str, Any]) -> None:
        if not data:
            return
        sets = ", ".join(f"{k} = ?" for k in data)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", tuple(data.values()) + (row_id,))

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )

    def backup_to(self, dest_path: str) -> None:
        with self._lock:
            dest = sqlite3.connect(dest_path)
            try:
                self._conn.backup(dest)
            finally:
                dest.close()

    def restore_from(self, src_path: str) -> None:
        with self._lock:
            src = sqlite3.connect(src_path)
            try:
                src.backup(self._conn)
            finally:
                src.close()
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
