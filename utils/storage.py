"""Persistent user/bot data storage.

Two backends are supported:

* :class:`JsonStore` — single ``panel_db.json`` file (matches the legacy
  monolith, zero dependencies).
* :class:`SqliteStore` — SQLite database (recommended for production; enables
  concurrent reads, indexed queries and ACID writes).

Both expose the same small API so the rest of the bot is backend-agnostic:

``get_user(uid)`` / ``upsert_user(...)`` / ``is_banned(uid)`` /
``set_banned(uid, value)`` / ``get_bots(uid)`` / ``upsert_bot(...)`` /
``audit(uid, action, detail)`` / ``load_all()`` / ``save_all()``
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import AUDIT_FILE, DB_FILE, SETTINGS_FILE

DEFAULT_DB: Dict[str, Any] = {
    "users": {},
    "bots": {},
    "settings": {},
    "audit": [],
    "banned": {},
    "scheduled_broadcasts": [],
}

_lock = threading.RLock()


# ════════════════════════════════════════════════════════════════════
#  JSON store (legacy-compatible)
# ════════════════════════════════════════════════════════════════════


class JsonStore:
    """File-backed JSON store with an in-memory cache and write-through."""

    def __init__(self, path: Path = DB_FILE) -> None:
        self.path = Path(path)
        self._cache: Optional[Dict[str, Any]] = None
        self._dirty = False

    # -- internal -------------------------------------------------------
    def _load(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._cache = json.loads(json.dumps(DEFAULT_DB))
            return self._cache
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            data = {}
        # Merge defaults so missing keys never KeyError downstream.
        merged: Dict[str, Any] = json.loads(json.dumps(DEFAULT_DB))
        for key, val in data.items():
            if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
                merged[key].update(val)
            else:
                merged[key] = val
        self._cache = merged
        return self._cache

    def save(self, data: Optional[Dict[str, Any]] = None) -> None:
        with _lock:
            if data is not None:
                self._cache = data
            if self._cache is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)
            self._dirty = False

    # -- public API -----------------------------------------------------
    def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        return self._load()["users"].get(str(uid))

    def upsert_user(self, uid: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _lock:
            data = self._load()
            users = data["users"]
            key = str(uid)
            user = users.get(key, {"uid": uid, "joined_at": time.time()})
            user.update(fields)
            user["uid"] = uid
            users[key] = user
            self.save(data)
            return user

    def is_banned(self, uid: int) -> bool:
        return bool(self._load()["banned"].get(str(uid), False))

    def set_banned(self, uid: int, value: bool) -> None:
        with _lock:
            data = self._load()
            data["banned"][str(uid)] = bool(value)
            self.save(data)

    def get_bots(self, uid: int) -> List[Dict[str, Any]]:
        return [
            b for b in self._load()["bots"].values() if b.get("owner_id") == uid
        ]

    def upsert_bot(self, bot_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _lock:
            data = self._load()
            bots = data["bots"]
            bot = bots.get(bot_id, {"bot_id": bot_id})
            bot.update(fields)
            bot["bot_id"] = bot_id
            bots[bot_id] = bot
            self.save(data)
            return bot

    def delete_bot(self, bot_id: str) -> None:
        with _lock:
            data = self._load()
            data["bots"].pop(bot_id, None)
            self.save(data)

    def audit(self, uid: int, action: str, detail: str = "") -> None:
        with _lock:
            data = self._load()
            entry = {
                "uid": uid,
                "action": action,
                "detail": detail,
                "ts": time.time(),
            }
            data["audit"].append(entry)
            data["audit"] = data["audit"][-500:]
            self.save(data)

    def load_all(self) -> Dict[str, Any]:
        return self._load()

    def save_all(self, data: Dict[str, Any]) -> None:
        self.save(data)


# ════════════════════════════════════════════════════════════════════
#  SQLite store (production)
# ════════════════════════════════════════════════════════════════════


class SqliteStore:
    """SQLite-backed store implementing the same API as :class:`JsonStore`."""

    def __init__(self, path: Path = DB_FILE.with_suffix(".sqlite")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                data TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY,
                data TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS banned (
                uid TEXT PRIMARY KEY,
                banned INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid INTEGER NOT NULL,
                action TEXT NOT NULL,
                detail TEXT,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def _now(self) -> float:
        return time.time()

    def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT data FROM users WHERE uid = ?", (str(uid),)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data["uid"] = uid
        return data

    def upsert_user(self, uid: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _lock:
            now = self._now()
            existing = self.get_user(uid) or {}
            existing.update(fields)
            existing["uid"] = uid
            self._conn.execute(
                "INSERT INTO users(uid, data, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (str(uid), json.dumps(existing), now),
            )
            self._conn.commit()
            return existing

    def is_banned(self, uid: int) -> bool:
        row = self._conn.execute(
            "SELECT banned FROM banned WHERE uid = ?", (str(uid),)
        ).fetchone()
        return bool(row and row["banned"])

    def set_banned(self, uid: int, value: bool) -> None:
        with _lock:
            self._conn.execute(
                "INSERT INTO banned(uid, banned) VALUES(?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET banned=excluded.banned",
                (str(uid), int(bool(value))),
            )
            self._conn.commit()

    def get_bots(self, uid: int) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT data FROM bots WHERE json_extract(data, '$.owner_id') = ?",
            (uid,),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            b = json.loads(row["data"])
            b["bot_id"] = b.get("bot_id")
            out.append(b)
        return out

    def upsert_bot(self, bot_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _lock:
            now = self._now()
            existing = self._conn.execute(
                "SELECT data FROM bots WHERE bot_id = ?", (bot_id,)
            ).fetchone()
            data = json.loads(existing["data"]) if existing else {}
            data.update(fields)
            data["bot_id"] = bot_id
            self._conn.execute(
                "INSERT INTO bots(bot_id, data, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(bot_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                (bot_id, json.dumps(data), now),
            )
            self._conn.commit()
            return data

    def delete_bot(self, bot_id: str) -> None:
        with _lock:
            self._conn.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
            self._conn.commit()

    def audit(self, uid: int, action: str, detail: str = "") -> None:
        with _lock:
            self._conn.execute(
                "INSERT INTO audit(uid, action, detail, ts) VALUES(?, ?, ?, ?)",
                (uid, action, detail, self._now()),
            )
            self._conn.commit()

    def load_all(self) -> Dict[str, Any]:
        # Compatibility shim; callers wanting everything should query directly.
        return {"users": {}, "bots": {}, "audit": []}

    def save_all(self, data: Dict[str, Any]) -> None:
        # No-op: SQLite writes are immediate per operation.
        return None


# ════════════════════════════════════════════════════════════════════
#  Default store instance
# ════════════════════════════════════════════════════════════════════


def get_store() -> Any:
    """Return the configured store (JSON by default; SQLite if enabled)."""
    use_sqlite = os.environ.get("USE_SQLITE", "0") == "1"
    if use_sqlite:
        return SqliteStore()
    return JsonStore()


store = get_store()

# Backwards-compatible module-level aliases used by legacy code / tests.
db_load = store.load_all
db_save = store.save_all


def get_or_create_user(uid: int, ref: Optional[int] = None) -> Dict[str, Any]:
    """Fetch a user record, creating it if it does not exist."""
    user = store.get_user(uid)
    if user is None:
        user = store.upsert_user(
            uid,
            {
                "uid": uid,
                "joined_at": time.time(),
                "plan": "free",
                "banned": False,
                "ref": ref,
                "tokens": 0,
            },
        )
    return user
