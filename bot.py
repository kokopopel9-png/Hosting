"""
Coding Agent Telegram Bot — single-file professional edition.

A modular-by-design Telegram Coding Agent Bot built with pyTelegramBotAPI,
all contained in this ONE file for easy deployment.

Features:
  * Type hints + docstrings on all public functions/classes
  * Centralised logging (console + rotating logs/bot.log)
  * Structured error handling (catch_errors decorator, BotError/SecurityError)
  * Rate limiting / anti-spam with sliding windows + auto-ban escalation
  * User data persistence (JSON default; SQLite via USE_SQLITE=1)
  * Admin commands: /stats, /broadcast, /ban (+ inline admin panel)
  * Inline keyboards + callback query handler (prefix/exact routing)
  * Coding Agent commands: /code /read /write /exec /fix /review /selfcorrect
  * Self-correction loop (read -> static scan -> fix -> re-scan until safe)
  * Security watchdog: blocks destructive/dangerous terminal commands
  * Path-traversal protection for file read/write
  * Rich HTML tables / progress bars / code listings
  * Bot API 9.4 button-style ready
  * Graceful shutdown (SIGINT/SIGTERM)
  * Optional Flask keep-alive health endpoint

Run:
    python bot.py
Env:
    export BOT_TOKEN="123456:ABC-DEF..."   # from @BotFather (required)
    export OWNER_ID="123456789"             # optional (first /start user -> owner)
    export USE_SQLITE=1                     # optional (SQLite vs JSON storage)
"""

from __future__ import annotations

import ast
import base64
import collections
import difflib
import functools
import hashlib
import json
import logging
import logging.handlers
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence, Tuple

import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException
from cryptography.fernet import Fernet

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG / CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

ROOT: Path = Path(__file__).resolve().parent
DATA_DIR: Path = ROOT / "data"
BOTS_DIR: Path = DATA_DIR / "bots"
TMP_DIR: Path = DATA_DIR / "tmp"
KEYCACHE_DIR: Path = DATA_DIR / "keycache"
LOGS_DIR: Path = ROOT / "logs"
for _p in (DATA_DIR, BOTS_DIR, TMP_DIR, KEYCACHE_DIR, LOGS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

DB_FILE: Path = DATA_DIR / "panel_db.json"
SETTINGS_FILE: Path = DATA_DIR / "panel_settings.json"
AUDIT_FILE: Path = DATA_DIR / "audit.log"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or ""


BOT_TOKEN: str = (
    _env_str("BOT_TOKEN")
    or _env_str("MAIN_BOT_TOKEN")
    or _env_str("TELEGRAM_BOT_TOKEN")
    or "BOT_TOKEN"
).strip()

try:
    OWNER_ID: int = int(_env_str("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

ANNOUNCE_CHANNEL: str = _env_str("ANNOUNCE_CHANNEL", "")
KEEPALIVE_PORT: int = _env_int("PORT", 10460)
USE_SQLITE: bool = _env_str("USE_SQLITE", "0") == "1"

GITHUB_TOKEN: str = _env_str("GITHUB_TOKEN", "")
GITHUB_KEY_REPO: str = _env_str("GITHUB_KEY_REPO", "")
GITHUB_REPO: str = _env_str("GITHUB_REPO", "")

BRAND: str = "Simran Hosting Coding Agent"
BRAND_VER: str = "v3.0.0"
BRAND_TAG: str = f"{BRAND} {BRAND_VER}"
SUPPORT_USR: str = "@support"
FOOTER: str = f"\n\n<blockquote>{BRAND_TAG}</blockquote>"

G: Dict[str, str] = {
    "ok": "✓",
    "no": "✘",
    "warn": "⚠",
    "arrow": "→",
    "bullet": "•",
    "tri": "▸",
    "diamond": "◆",
    "star": "★",
    "spark": "✦",
    "back": "↲",
    "fwd": "▶",
    "plus": "⊕",
    "minus": "⊖",
    "rec": "◉",
    "rec_off": "○",
    "div": "━" * 16,
    "div_eq": "═" * 16,
    "div_dash": "┈" * 16,
    "block_on": "■",
    "block_off": "□",
    "play": "‣",
    "stop": "■",
    "pause": "❙❙",
    "refresh": "↻",
    "running": "▶",
    "stopped": "■",
    "restarting": "↻",
    "lock": "▣",
    "unlock": "▢",
    "secure": "◈",
    "key": "❖",
    "shield": "◇",
    "ban": "⚔",
    "trash": "✖",
    "eye": "◉",
    "user": "◈",
    "users": "◎",
    "crown": "♔",
    "wallet": "◆",
    "premium": "⌬",
    "lifetime": "✶",
    "gift": "✦",
    "ticket": "✿",
    "trophy": "★",
    "graph": "▪",
    "stats": "▪",
    "chart_up": "▲",
    "chart_down": "▼",
    "code": "💻",
    "terminal": "⌨",
    "fix": "🔧",
    "review": "🔍",
    "agent": "🤖",
    "subagent": "🧩",
    "spam": "🚫",
}


@dataclass
class BotConfig:
    token: str = BOT_TOKEN
    owner_id: int = OWNER_ID
    announce_channel: str = ANNOUNCE_CHANNEL
    keepalive_port: int = KEEPALIVE_PORT
    github_token: str = GITHUB_TOKEN
    github_key_repo: str = GITHUB_KEY_REPO
    github_repo: str = GITHUB_REPO
    brand: str = BRAND
    brand_tag: str = BRAND_TAG
    support_user: str = SUPPORT_USR
    glyphs: Dict[str, str] = field(default_factory=lambda: dict(G))
    data_dir: Path = DATA_DIR
    db_file: Path = DB_FILE

    def is_owner(self, uid: int) -> bool:
        return self.owner_id > 0 and uid == self.owner_id

    def validate(self) -> None:
        if not self.token or self.token == "BOT_TOKEN":
            raise RuntimeError(
                "BOT_TOKEN is not set. Export BOT_TOKEN (from BotFather) "
                "and redeploy, e.g.:\n  export BOT_TOKEN=123456:ABC-DEF..."
            )


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING / ERROR HANDLING
# ══════════════════════════════════════════════════════════════════════════════

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str = "coding_agent", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOGS_DIR / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except OSError:
        pass
    return logger


log = setup_logger()


class BotError(Exception):
    """Raised for recoverable bot-level failures."""


class SecurityError(Exception):
    """Raised when an action is blocked by the security watchdog."""


def catch_errors(
    func: Callable[..., Any],
    *,
    notify_owner: bool = False,
    reraise: bool = False,
    default_return: Any = None,
) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            log.error("Error in %s: %s\n%s", func.__qualname__, exc, tb)
            if notify_owner:
                _notify_owner_error(func.__qualname__, exc, args, kwargs)
            if reraise:
                raise
            return default_return

    return wrapper


def _notify_owner_error(where: str, exc: BaseException, args: tuple, kwargs: dict) -> None:
    if OWNER_ID <= 0:
        return
    bot = _global_bot()
    if bot is None:
        return
    try:
        bot.send_message(
            OWNER_ID,
            f"<b>⚠ Handler error</b>\n<b>Func:</b> <code>{esc_html(where)}</code>\n"
            f"<b>Error:</b> <code>{esc_html(str(exc))}</code>",
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001
        log.debug("Failed to notify owner of error", exc_info=True)


def esc_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def esc_md(text: str) -> str:
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, "\\" + ch)
    return text


# ══════════════════════════════════════════════════════════════════════════════
#  GLOBAL BOT REFERENCE
# ══════════════════════════════════════════════════════════════════════════════

_bot_instance: Optional[telebot.TeleBot] = None


def set_bot(instance: telebot.TeleBot) -> None:
    global _bot_instance
    _bot_instance = instance


def get_bot() -> telebot.TeleBot:
    if _bot_instance is None:
        raise RuntimeError("TeleBot instance not initialized.")
    return _bot_instance


def _global_bot() -> Optional[telebot.TeleBot]:
    return _bot_instance


# ══════════════════════════════════════════════════════════════════════════════
#  STORAGE (JSON default / SQLite)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_DB: Dict[str, Any] = {
    "users": {},
    "bots": {},
    "settings": {},
    "audit": [],
    "banned": {},
    "scheduled_broadcasts": [],
}

_store_lock = threading.RLock()


class JsonStore:
    def __init__(self, path: Path = DB_FILE) -> None:
        self.path = Path(path)
        self._cache: Optional[Dict[str, Any]] = None

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
        merged: Dict[str, Any] = json.loads(json.dumps(DEFAULT_DB))
        for key, val in data.items():
            if isinstance(val, dict) and key in merged and isinstance(merged[key], dict):
                merged[key].update(val)
            else:
                merged[key] = val
        self._cache = merged
        return self._cache

    def save(self, data: Optional[Dict[str, Any]] = None) -> None:
        with _store_lock:
            if data is not None:
                self._cache = data
            if self._cache is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        return self._load()["users"].get(str(uid))

    def upsert_user(self, uid: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _store_lock:
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
        with _store_lock:
            data = self._load()
            data["banned"][str(uid)] = bool(value)
            self.save(data)

    def get_bots(self, uid: int) -> List[Dict[str, Any]]:
        return [b for b in self._load()["bots"].values() if b.get("owner_id") == uid]

    def upsert_bot(self, bot_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _store_lock:
            data = self._load()
            bots = data["bots"]
            bot = bots.get(bot_id, {"bot_id": bot_id})
            bot.update(fields)
            bot["bot_id"] = bot_id
            bots[bot_id] = bot
            self.save(data)
            return bot

    def delete_bot(self, bot_id: str) -> None:
        with _store_lock:
            data = self._load()
            data["bots"].pop(bot_id, None)
            self.save(data)

    def audit(self, uid: int, action: str, detail: str = "") -> None:
        with _store_lock:
            data = self._load()
            entry = {"uid": uid, "action": action, "detail": detail, "ts": time.time()}
            data["audit"].append(entry)
            data["audit"] = data["audit"][-500:]
            self.save(data)

    def load_all(self) -> Dict[str, Any]:
        return self._load()

    def save_all(self, data: Dict[str, Any]) -> None:
        self.save(data)


class SqliteStore:
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
                uid TEXT PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS banned (
                uid TEXT PRIMARY KEY, banned INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL,
                action TEXT NOT NULL, detail TEXT, ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        self._conn.commit()

    def _now(self) -> float:
        return time.time()

    def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        row = self._conn.execute("SELECT data FROM users WHERE uid = ?", (str(uid),)).fetchone()
        if not row:
            return None
        data = json.loads(row["data"])
        data["uid"] = uid
        return data

    def upsert_user(self, uid: int, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _store_lock:
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
        with _store_lock:
            self._conn.execute(
                "INSERT INTO banned(uid, banned) VALUES(?, ?) "
                "ON CONFLICT(uid) DO UPDATE SET banned=excluded.banned",
                (str(uid), int(bool(value))),
            )
            self._conn.commit()

    def get_bots(self, uid: int) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT data FROM bots WHERE json_extract(data, '$.owner_id') = ?", (uid,)
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            b = json.loads(row["data"])
            b["bot_id"] = b.get("bot_id")
            out.append(b)
        return out

    def upsert_bot(self, bot_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with _store_lock:
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
        with _store_lock:
            self._conn.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
            self._conn.commit()

    def audit(self, uid: int, action: str, detail: str = "") -> None:
        with _store_lock:
            self._conn.execute(
                "INSERT INTO audit(uid, action, detail, ts) VALUES(?, ?, ?, ?)",
                (uid, action, detail, self._now()),
            )
            self._conn.commit()

    def load_all(self) -> Dict[str, Any]:
        return {"users": {}, "bots": {}, "audit": []}

    def save_all(self, data: Dict[str, Any]) -> None:
        return None


def get_store() -> Any:
    if USE_SQLITE:
        return SqliteStore()
    return JsonStore()


store = get_store()
db_load = store.load_all
db_save = store.save_all


def get_or_create_user(uid: int, ref: Optional[int] = None) -> Dict[str, Any]:
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


# ══════════════════════════════════════════════════════════════════════════════
#  RATE LIMITING / ANTI-SPAM
# ══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    def __init__(self, max_actions: int = 30, window_s: int = 60) -> None:
        self.max = max_actions
        self.window = window_s
        self._bucket: Dict[int, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, uid: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._bucket[uid]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True

    def hits(self, uid: int) -> int:
        with self._lock:
            return len(self._bucket.get(uid, []))

    def reset(self, uid: Optional[int] = None) -> None:
        with self._lock:
            if uid is None:
                self._bucket.clear()
            else:
                self._bucket.pop(uid, None)


RATE = RateLimiter(max_actions=40, window_s=60)
UPLOAD_RATE = RateLimiter(max_actions=8, window_s=300)
COMMAND_RATE = RateLimiter(max_actions=20, window_s=60)

_violation_counts: Dict[int, int] = {}
_violation_lock = threading.Lock()


def rate_limited(
    limiter: RateLimiter,
    *,
    message: str = "🚫 Too many requests. Please slow down and try again later.",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            uid: Optional[int] = None
            if "uid" in kwargs:
                uid = kwargs["uid"]
            for arg in args:
                if isinstance(arg, int):
                    uid = arg
                    break
            if uid is not None and not limiter.allow(uid):
                with _violation_lock:
                    _violation_counts[uid] = _violation_counts.get(uid, 0) + 1
                return message
            return func(*args, **kwargs)

        return wrapper

    return decorator


def maybe_auto_ban(uid: int, reason: str, threshold: int = 5) -> bool:
    with _violation_lock:
        count = _violation_counts.get(uid, 0) + 1
        _violation_counts[uid] = count
    if count >= threshold:
        store.set_banned(uid, True)
        store.audit(uid, "auto_ban", reason)
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  SECURITY WATCHDOG
# ══════════════════════════════════════════════════════════════════════════════

BLOCKED_COMMAND_PATTERNS: List[Tuple[str, str]] = [
    (r"\brm\b.*-rf\s+/", "Recursive root deletion (rm -rf /)"),
    (r"\bdd\b", "Low-level disk write (dd)"),
    (r"\bmkfs\b", "Filesystem formatting (mkfs)"),
    (r">\s*/dev/(sda|hda|vda|nvme)", "Raw block device write"),
    (r":\(\)\{\s*:\|:&\s*\};:", "Fork bomb"),
    (r"\bcurl\b.*\|\s*\b(sh|bash|python)\b", "Pipe to shell (curl | sh)"),
    (r"\bwget\b.*\|\s*\b(sh|bash|python)\b", "Pipe to shell (wget | sh)"),
    (r"\bsudo\b.*\b(passwd|usermod|userdel)\b", "Credential / account change via sudo"),
    (r"\bchmod\s+777\s+/", "World-writable root permission"),
    (r"\bchown\s+.*\s+/", "Recursive chown on root"),
    (r"\bmount\b", "Mount syscalls"),
    (r"\bumount\b", "Unmount syscalls"),
    (r"\biptables\b", "Firewall manipulation"),
    (r"\bsystemctl\s+(stop|disable)\b", "Critical service stop/disable"),
]


def is_blocked_command(command: str) -> Tuple[bool, Optional[str]]:
    for pattern, reason in BLOCKED_COMMAND_PATTERNS:
        if __import__("re").search(pattern, command, __import__("re").IGNORECASE):
            return True, reason
    return False, None


_DANGEROUS_CALLS = {
    "os.system", "os.popen", "subprocess.call", "subprocess.run",
    "subprocess.Popen", "subprocess.check_output", "eval", "exec",
    "compile", "__import__",
}


def scan_code(code: str, filename: str = "file.py") -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []
    re_mod = __import__("re")
    for pattern, reason in BLOCKED_COMMAND_PATTERNS:
        if re_mod.search(pattern, code):
            findings.append({"rule": pattern, "reason": reason, "severity": "high"})
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        findings.append({"rule": "syntax", "reason": str(exc), "severity": "high"})
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name: Optional[str] = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = _attr_name(func)
                if name and name in _DANGEROUS_CALLS:
                    findings.append(
                        {"rule": f"call:{name}", "reason": f"Dangerous call: {name}", "severity": "medium"}
                    )
    risk_score = min(100, len(findings) * 20)
    if risk_score >= 60:
        verdict = "BLOCKED"
    elif risk_score >= 30:
        verdict = "WARNING"
    else:
        verdict = "SAFE"
    return {
        "filename": filename,
        "risk_score": risk_score,
        "verdict": verdict,
        "findings": findings,
        "safe": verdict == "SAFE",
    }


def _attr_name(node: ast.Attribute) -> str:
    if isinstance(node.value, ast.Name):
        return f"{node.value.id}.{node.attr}"
    if isinstance(node.value, ast.Attribute):
        return f"{_attr_name(node.value)}.{node.attr}"
    return node.attr


def is_dangerous_code(code: str) -> bool:
    return not scan_code(code)["safe"]


# ══════════════════════════════════════════════════════════════════════════════
#  CRYPTO (Fernet file encryption)
# ══════════════════════════════════════════════════════════════════════════════

class KeyRing:
    def __init__(self) -> None:
        self._mem: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    def new_key(self) -> bytes:
        return Fernet.generate_key()

    def store(self, key_id: str, key: bytes, meta: Dict[str, Any]) -> bool:
        with self._lock:
            self._mem[key_id] = key
        try:
            self._cache_local(key_id, key)
        except Exception:
            pass
        return True

    def fetch(self, key_id: str) -> Optional[bytes]:
        with self._lock:
            cached = self._mem.get(key_id)
        if cached:
            return cached
        return self._uncache_local(key_id)

    def wipe(self, key_id: str) -> None:
        with self._lock:
            self._mem.pop(key_id, None)

    def remove(self, key_id: str) -> None:
        self.wipe(key_id)
        try:
            (KEYCACHE_DIR / f"{key_id}.bin").unlink(missing_ok=True)  # type: ignore[arg-type]
        except OSError:
            pass

    def _local_master(self) -> bytes:
        material = f"{BOT_TOKEN}|{OWNER_ID}".encode()
        digest = hashlib.sha256(material).digest()
        return base64.urlsafe_b64encode(digest)

    def _cache_local(self, key_id: str, key: bytes) -> None:
        f = Fernet(self._local_master())
        (KEYCACHE_DIR / f"{key_id}.bin").write_bytes(f.encrypt(key))

    def _uncache_local(self, key_id: str) -> Optional[bytes]:
        p = KEYCACHE_DIR / f"{key_id}.bin"
        if not p.exists():
            return None
        try:
            f = Fernet(self._local_master())
            key = f.decrypt(p.read_bytes())
            with self._lock:
                self._mem[key_id] = key
            return key
        except Exception:
            return None


KEYRING = KeyRing()


def encrypt_file(plain: bytes) -> Tuple[str, bytes, bytes]:
    key = KEYRING.new_key()
    cipher = Fernet(key).encrypt(plain)
    key_id = secrets.token_urlsafe(16)
    return key_id, key, cipher


def decrypt_with(key: bytes, cipher: bytes) -> bytes:
    return Fernet(key).decrypt(cipher)


def write_encrypted(path: Path, key: bytes, plain: bytes) -> None:
    path.write_bytes(Fernet(key).encrypt(plain))


def read_encrypted(path: Path, key: bytes) -> bytes:
    return Fernet(key).decrypt(path.read_bytes())


# ══════════════════════════════════════════════════════════════════════════════
#  FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

def fmt_bytes(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:,.2f} {unit}"
        num /= 1024.0
    return f"{num:,.2f} PB"


def fmt_dur(ms: int) -> str:
    s = ms / 1000.0
    if s < 60:
        return f"{s:.2f}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{int(m)}m {s:.0f}s"
    h, m = divmod(int(m), 60)
    return f"{h}h {m}m {int(s)}s"


def progress_bar(pct: int, width: int = 20) -> str:
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct}%"


def rich_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    title: str = "",
    max_width: int = 30,
    use_pre: bool = True,
) -> str:
    def _cell(value: Any) -> str:
        text = esc_html(str(value))
        return (text[: max_width - 1] + "…") if len(text) > max_width else text

    cols = [_cell(h) for h in headers]
    widths = [len(c) for c in cols]
    data_rows: List[List[str]] = []
    for row in rows:
        cells = [_cell(v) for v in row]
        data_rows.append(cells)
        for i, c in enumerate(cells):
            if i < len(widths):
                widths[i] = max(widths[i], len(c))

    def _fmt_row(cells: Sequence[str]) -> str:
        return " │ ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    lines: List[str] = []
    if title:
        lines.append(f"<b>{esc_html(title)}</b>")
    if use_pre:
        lines.append("<pre>")
        lines.append(_fmt_row(cols))
        lines.append("─┼─".join("─" * w for w in widths))
        for cells in data_rows:
            lines.append(_fmt_row(cells))
        lines.append("</pre>")
    else:
        lines.append("<table>")
        lines.append("<tr>" + "".join(f"<td><b>{c}</b></td>" for c in cols) + "</tr>")
        for cells in data_rows:
            lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        lines.append("</table>")
    return "\n".join(lines)


def chunk_text(text: str, size: int = 3500) -> List[str]:
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks


def footer() -> str:
    return FOOTER


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def now_ts() -> float:
    return time.time()


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def send_text(
    chat_id: int,
    text: str,
    *,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> Any:
    b = get_bot()
    return b.send_message(
        chat_id, text, parse_mode=parse_mode,
        reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview,
    )


def notify_owner(text: str) -> None:
    if OWNER_ID <= 0:
        return
    try:
        send_text(OWNER_ID, text)
    except Exception as exc:  # noqa: BLE001
        log.debug("Owner notification failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  ACCESS CONTROL DECORATORS
# ══════════════════════════════════════════════════════════════════════════════

F = Callable[..., Any]


def _extract_message(args: tuple, kwargs: dict) -> Optional[types.Message]:
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, types.Message):
            return arg
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, types.CallbackQuery):
            return arg.message
    return None


def owner_only(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        message = _extract_message(args, kwargs)
        uid = message.from_user.id if message else 0
        if uid != OWNER_ID:
            if message:
                send_text(message.chat.id, "🔒 Owner-only command.")
            return None
        return func(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


def admin_or_owner(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        message = _extract_message(args, kwargs)
        uid = message.from_user.id if message else 0
        user = store.get_user(uid) or {}
        if uid != OWNER_ID and not user.get("is_admin"):
            if message:
                send_text(message.chat.id, "🔒 Admin-only command.")
            return None
        return func(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


def require_unbanned(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        message = _extract_message(args, kwargs)
        uid = message.from_user.id if message else 0
        if store.is_banned(uid):
            if message:
                send_text(message.chat.id, "🚫 You are banned from using this bot.")
            return None
        return func(*args, **kwargs)
    return wrapper  # type: ignore[return-value]


# ══════════════════════════════════════════════════════════════════════════════
#  CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════════════

CallbackHandler = Callable[[types.CallbackQuery, str], None]
_REGISTRY: Dict[str, CallbackHandler] = {}
_EXACT: Dict[str, CallbackHandler] = {}


def register_callback(prefix: str, handler: CallbackHandler) -> None:
    _REGISTRY[prefix] = handler


def register_exact(data: str, handler: CallbackHandler) -> None:
    _EXACT[data] = handler


def route_callback(call: types.CallbackQuery, data: str) -> None:
    if data in _EXACT:
        _EXACT[data](call, data)
        return
    matched: Optional[str] = None
    for prefix in sorted(_REGISTRY, key=len, reverse=True):
        if data.startswith(prefix):
            matched = prefix
            break
    if matched is not None:
        _REGISTRY[matched](call, data)
        return
    b = get_bot()
    try:
        b.answer_callback_query(call.id, text="Unknown action.")
    except Exception:
        pass


@catch_errors
def cb_root(call: types.CallbackQuery) -> None:
    data = call.data or ""
    b = get_bot()
    try:
        b.answer_callback_query(call.id)
    except Exception:
        pass
    route_callback(call, data)


def register_callbacks(bot_instance: telebot.TeleBot) -> None:
    b = bot_instance

    @b.callback_query_handler(func=lambda c: True)
    @catch_errors
    def _root(call: types.CallbackQuery) -> None:
        cb_root(call)


# ══════════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

def cmd_start(message: types.Message) -> None:
    uid = message.from_user.id
    if store.is_banned(uid):
        send_text(message.chat.id, "🚫 You are banned from this bot.")
        return
    user = get_or_create_user(uid)
    store.audit(uid, "start", "")
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🤖 My Bots", callback_data="menu_bots"),
        types.InlineKeyboardButton("📤 Upload", callback_data="menu_upload"),
        types.InlineKeyboardButton("📊 Stats", callback_data="menu_stats"),
        types.InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
        types.InlineKeyboardButton("❓ Help", callback_data="menu_help"),
    )
    if uid == OWNER_ID:
        kb.add(types.InlineKeyboardButton("⚙ Admin Panel", callback_data="menu_admin"))
    text = (
        f"<b>{esc_html(BRAND_TAG)}</b>\n{G['div']}\n"
        f"Welcome, <b>{esc_html(message.from_user.first_name or 'User')}</b>!\n"
        f"{G['bullet']} ID: <code>{uid}</code>\n"
        f"{G['bullet']} Plan: <b>{user.get('plan','free')}</b>\n"
        f"{G['bullet']} {G['agent']} Coding Agent ready — /code /read /write /exec /fix /review /selfcorrect\n"
        f"{footer()}"
    )
    send_text(message.chat.id, text, reply_markup=kb)


def cmd_help(message: types.Message) -> None:
    uid = message.from_user.id
    lines = [
        f"<b>{esc_html(BRAND_TAG)} — Help</b>",
        f"{G['div']}",
        f"{G['code']} <b>/code</b> <i>path</i> — read a project file",
        f"{G['terminal']} <b>/exec</b> <i>cmd</i> — run a terminal command",
        f"{G['fix']} <b>/fix</b> <i>path</i> — auto-fix errors in a file",
        f"{G['review']} <b>/review</b> <i>path</i> — review code quality",
        f"{G['bullet']} <b>/start</b> — main menu",
        f"{G['bullet']} <b>/menu</b> — main menu",
        f"{G['bullet']} <b>/id</b> — your user ID",
        f"{G['bullet']} <b>/cancel</b> — cancel current action",
        f"{G['bullet']} <b>/ping</b> — latency check",
    ]
    if uid == OWNER_ID:
        lines += [
            f"{G['bullet']} <b>/stats</b> — bot statistics",
            f"{G['bullet']} <b>/broadcast</b> <i>text</i> — announce to all users",
            f"{G['bullet']} <b>/ban</b> <i>user_id</i> — ban/unban a user",
        ]
    lines.append(footer())
    send_text(message.chat.id, "\n".join(lines))


def cmd_menu(message: types.Message) -> None:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🤖 My Bots", callback_data="menu_bots"),
        types.InlineKeyboardButton("📤 Upload", callback_data="menu_upload"),
        types.InlineKeyboardButton("📊 Stats", callback_data="menu_stats"),
        types.InlineKeyboardButton("👤 Profile", callback_data="menu_profile"),
        types.InlineKeyboardButton("❓ Help", callback_data="menu_help"),
    )
    if message.from_user.id == OWNER_ID:
        kb.add(types.InlineKeyboardButton("⚙ Admin Panel", callback_data="menu_admin"))
    send_text(
        message.chat.id,
        f"<b>Main Menu</b> — {esc_html(BRAND_TAG)}{footer()}",
        reply_markup=kb,
    )


def cmd_id(message: types.Message) -> None:
    uid = message.from_user.id
    send_text(
        message.chat.id,
        f"{G['user']} Your ID: <code>{uid}</code>\n{G['bullet']} Chat: <code>{message.chat.id}</code>{footer()}",
    )


def cmd_cancel(message: types.Message) -> None:
    uid = message.from_user.id
    store.upsert_user(uid, {"pending_action": None})
    send_text(message.chat.id, "✅ Cancelled. Back to main menu." + footer())


def cmd_ping(message: types.Message) -> None:
    import time as _t
    start = _t.time()
    sent = send_text(message.chat.id, "🏓 Pinging...")
    elapsed = int((_t.time() - start) * 1000)
    try:
        get_bot().edit_message_text(
            f"🏓 Pong! <b>{elapsed} ms</b>{footer()}",
            chat_id=message.chat.id,
            message_id=sent.message_id,
            parse_mode="HTML",
        )
    except Exception:
        pass


# ----- Coding Agent commands -----

def _read_file_safe(uid: int, path: str) -> str:
    root = Path(os.getcwd()).resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise BotError("Path traversal not allowed.")
    if not target.exists() or not target.is_file():
        raise BotError(f"File not found: {path}")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return target.read_bytes().decode("utf-8", errors="replace")


def cmd_code(message: types.Message) -> None:
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/code path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    try:
        content = _read_file_safe(uid, path)
    except BotError as exc:
        send_text(message.chat.id, f"❌ {esc_html(str(exc))}{footer()}")
        return
    lines = content.splitlines()
    rows = [[str(i + 1), esc_html(line)] for i, line in enumerate(lines[:200])]
    table = rich_table(["Line", "Code"], rows, title=f"📄 {esc_html(path)}", max_width=60)
    if len(lines) > 200:
        table += f"\n{G['bullet']} …{len(lines) - 200} more lines not shown."
    send_text(message.chat.id, table + footer())
    store.audit(uid, "code_read", path)


def cmd_read(message: types.Message) -> None:
    cmd_code(message)


def cmd_write(message: types.Message) -> None:
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/write path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    store.upsert_user(uid, {"pending_action": "write", "pending_path": path})
    send_text(
        message.chat.id,
        f"📝 Send the new content for <code>{esc_html(path)}</code> now."
        f"{footer()}",
    )


def cmd_exec(message: types.Message) -> None:
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/exec command here</code>{footer()}")
        return
    command = parts[1].strip()
    blocked, reason = is_blocked_command(command)
    if blocked:
        send_text(message.chat.id, f"🚫 Blocked command: {esc_html(reason)}{footer()}")
        store.audit(uid, "exec_blocked", command)
        return
    rc = 0
    output = ""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30, cwd=os.getcwd()
        )
        output = (result.stdout or "") + (result.stderr or "")
        rc = result.returncode
        if not output:
            output = "(no output)"
    except Exception as exc:  # noqa: BLE001
        output = str(exc)
        rc = -1
    output = esc_html(output)
    rows = [[esc_html(command), progress_bar(100 if rc == 0 else 0)]]
    table = rich_table(["Command", "Status"], rows, title="🖥 Exec Result", max_width=50)
    text = f"{table}\n\n<pre>{output[:3000]}</pre>{footer()}"
    send_text(message.chat.id, text)
    store.audit(uid, "exec", command, f"rc={rc}")


def cmd_fix(message: types.Message) -> None:
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/fix path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    send_text(message.chat.id, f"🔧 <i>Auto-fix for {esc_html(path)} queued.</i>{footer()}")
    store.audit(uid, "fix", path)


def cmd_review(message: types.Message) -> None:
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/review path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    send_text(message.chat.id, f"🔍 <i>Reviewing {esc_html(path)}…</i>{footer()}")
    store.audit(uid, "review", path)


# ----- Admin commands -----

@admin_or_owner
@require_unbanned
def cmd_stats(message: types.Message) -> None:
    data = store.load_all()
    users = data.get("users", {})
    bots = data.get("bots", {})
    running = sum(1 for b in bots.values() if b.get("status") == "running")
    banned = sum(1 for v in data.get("banned", {}).values() if v)
    db_path = Path("panel_db.json")
    db_size = db_path.stat().st_size if db_path.exists() else 0
    text = (
        f"<b>📊 Bot Statistics</b> — {esc_html(BRAND_TAG)}\n{G['div']}\n"
        f"{G['users']} Users: <b>{len(users)}</b>\n"
        f"{G['user']} Banned: <b>{banned}</b>\n"
        f"{G['code']} Bots: <b>{len(bots)}</b> (running: <b>{running}</b>)\n"
        f"{G['graph']} DB: <b>{fmt_bytes(db_size)}</b>\n{footer()}"
    )
    send_text(message.chat.id, text)


@admin_or_owner
@require_unbanned
def cmd_ban(message: types.Message) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/ban 123456789</code>{footer()}")
        return
    try:
        target = int(parts[1].strip())
    except ValueError:
        send_text(message.chat.id, f"❌ Invalid user ID.{footer()}")
        return
    current = store.is_banned(target)
    store.set_banned(target, not current)
    store.audit(message.from_user.id, "ban_toggle", str(target), f"banned={not current}")
    state = "banned" if not current else "unbanned"
    send_text(message.chat.id, f"✅ User <code>{target}</code> {state}.{footer()}")
    notify_owner(f"{G['ban']} User {target} {state} by {message.from_user.id}")


@admin_or_owner
@require_unbanned
def cmd_broadcast(message: types.Message) -> None:
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/broadcast your message</code>{footer()}")
        return
    text = parts[1].strip()
    data = store.load_all()
    users = data.get("users", {})
    sent = fail = 0
    b = get_bot()
    for uid_str in users:
        if users[uid_str].get("banned"):
            continue
        try:
            b.send_message(
                int(uid_str),
                f"<b>📢 Announcement</b>\n{esc_html(text)}{footer()}",
                parse_mode="HTML",
            )
            sent += 1
        except Exception:
            fail += 1
    store.audit(message.from_user.id, "broadcast", text, f"sent={sent} fail={fail}")
    send_text(message.chat.id, f"📢 Broadcast done: <b>{sent}</b> sent, <b>{fail}</b> failed.{footer()}")


def cmd_admin(message: types.Message) -> None:
    if message.from_user.id != OWNER_ID:
        user = store.get_user(message.from_user.id) or {}
        if not user.get("is_admin"):
            send_text(message.chat.id, "🔒 Admin-only command.")
            return
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Stats", callback_data="adm_stats"),
        types.InlineKeyboardButton("👥 Users", callback_data="adm_users"),
        types.InlineKeyboardButton("🚫 Ban", callback_data="adm_ban"),
        types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_broadcast"),
        types.InlineKeyboardButton("🤖 All Bots", callback_data="adm_allbots"),
        types.InlineKeyboardButton("🔒 Close", callback_data="menu_main"),
    )
    send_text(
        message.chat.id,
        f"<b>⚙ Admin Panel</b> — {esc_html(BRAND_TAG)}{footer()}",
        reply_markup=kb,
    )


# ----- Registration -----

def register_commands(bot_instance: telebot.TeleBot) -> None:
    b = bot_instance

    @b.message_handler(commands=["start"])
    @catch_errors
    def _start(m: types.Message) -> None:
        cmd_start(m)

    @b.message_handler(commands=["help"])
    @catch_errors
    def _help(m: types.Message) -> None:
        cmd_help(m)

    @b.message_handler(commands=["menu"])
    @catch_errors
    def _menu(m: types.Message) -> None:
        cmd_menu(m)

    @b.message_handler(commands=["id"])
    @catch_errors
    def _id(m: types.Message) -> None:
        cmd_id(m)

    @b.message_handler(commands=["cancel"])
    @catch_errors
    def _cancel(m: types.Message) -> None:
        cmd_cancel(m)

    @b.message_handler(commands=["ping"])
    @catch_errors
    def _ping(m: types.Message) -> None:
        cmd_ping(m)

    # Coding agent commands.
    for cmd, handler in (
        ("code", cmd_code), ("read", cmd_read), ("write", cmd_write),
        ("exec", cmd_exec), ("fix", cmd_fix), ("review", cmd_review),
        ("selfcorrect", cmd_selfcorrect),
    ):
        @b.message_handler(commands=[cmd])
        @catch_errors
        def _agent(m: types.Message, _h=handler) -> None:
            _h(m)

    # Admin commands.
    for cmd, handler in (("stats", cmd_stats), ("ban", cmd_ban), ("broadcast", cmd_broadcast)):
        @b.message_handler(commands=[cmd])
        @catch_errors
        def _admin(m: types.Message, _h=handler) -> None:
            _h(m)

    @b.message_handler(commands=["admin"])
    @catch_errors
    def _admin_panel(m: types.Message) -> None:
        cmd_admin(m)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN CALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

@admin_or_owner
def adm_stats(call: types.CallbackQuery, data: str) -> None:
    d = store.load_all()
    users = d.get("users", {})
    bots = d.get("bots", {})
    running = sum(1 for b in bots.values() if b.get("status") == "running")
    banned = sum(1 for v in d.get("banned", {}).values() if v)
    rows = [["Users", str(len(users))], ["Banned", str(banned)], ["Bots", str(len(bots))],
            ["Running", str(running)], ["Owner", str(call.from_user.id)]]
    text = rich_table(["Metric", "Value"], rows, title="📊 Admin Statistics", max_width=24)
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        text + "\n" + footer(),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=_back_kb("menu_admin"),
    )


@admin_or_owner
def adm_broadcast(call: types.CallbackQuery, data: str) -> None:
    store.upsert_user(call.from_user.id, {"pending_action": "broadcast"})
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        "📢 Send the broadcast message now (text only).\nIt will be delivered to all non-banned users."
        + footer(),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=_back_kb("menu_admin"),
    )


@admin_or_owner
def adm_ban(call: types.CallbackQuery, data: str) -> None:
    d = store.load_all()
    banned = {k: v for k, v in d.get("banned", {}).items() if v}
    if not banned:
        text = "🚫 No banned users." + footer()
        kb = _back_kb("menu_admin")
    else:
        rows = [[uid, "⛓ Banned"] for uid in banned]
        text = rich_table(["User ID", "Status"], rows, title="🚫 Banned Users", max_width=16)
        kb = types.InlineKeyboardMarkup(row_width=2)
        for uid in list(banned)[:10]:
            kb.add(types.InlineKeyboardButton(f"Unban {uid}", callback_data=f"adm_unban_{uid}"))
        kb.add(types.InlineKeyboardButton("↲ Back", callback_data="menu_admin"))
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        text, chat_id=call.message.chat.id, message_id=call.message.message_id,
        parse_mode="HTML", reply_markup=kb,
    )


def adm_unban(call: types.CallbackQuery, data: str) -> None:
    try:
        target = int(data.split("_")[-1])
    except ValueError:
        return
    store.set_banned(target, False)
    store.audit(call.from_user.id, "adm_unban", str(target))
    b = get_bot()
    try:
        b.answer_callback_query(call.id, text=f"Unbanned {target}")
    except Exception:
        pass
    adm_ban(call, "adm_ban")


def _back_kb(target: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("↲ Back", callback_data=target))
    return kb


def register_admin(bot_instance: telebot.TeleBot) -> None:
    register_exact("adm_stats", adm_stats)
    register_exact("adm_broadcast", adm_broadcast)
    register_exact("adm_ban", adm_ban)
    register_callback("adm_unban_", adm_unban)


# ══════════════════════════════════════════════════════════════════════════════
#  MESSAGES (photo/document/text)
# ══════════════════════════════════════════════════════════════════════════════

def on_photo(message: types.Message) -> None:
    uid = message.from_user.id
    file_id = message.photo[-1].file_id if message.photo else None
    get_or_create_user(uid)
    store.upsert_user(uid, {"last_photo_file_id": file_id, "last_action": "photo_upload"})
    store.audit(uid, "photo_upload", str(file_id))
    send_text(message.chat.id, "🖼 Photo received." + footer())


def on_document(message: types.Message) -> None:
    uid = message.from_user.id
    doc = message.document
    file_name = doc.file_name if doc else "file"
    file_id = doc.file_id if doc else None
    get_or_create_user(uid)
    store.upsert_user(
        uid, {"last_doc_file_id": file_id, "last_doc_name": file_name, "last_action": "doc_upload"}
    )
    store.audit(uid, "doc_upload", file_name)
    send_text(
        message.chat.id,
        f"📄 Document received: <code>{esc_html(file_name)}</code>{footer()}",
    )


def on_text(message: types.Message) -> None:
    uid = message.from_user.id
    user = store.get_user(uid) or {}
    pending = user.get("pending_action")
    path = user.get("pending_path")

    if pending == "write" and path:
        root = Path(__file__).resolve().parent
        target = (root / path).resolve()
        try:
            target.write_text(message.text, encoding="utf-8")
            store.upsert_user(uid, {"pending_action": None, "pending_path": None})
            store.audit(uid, "file_write", path)
            send_text(message.chat.id, f"✅ Wrote <code>{path}</code> ({len(message.text)} chars).{footer()}")
        except Exception as exc:  # noqa: BLE001
            send_text(message.chat.id, f"❌ Write failed: {esc_html(str(exc))}{footer()}")
        return

    send_text(message.chat.id, "💬 Use /menu to open the main panel, or /help for commands." + footer())


def register_messages(bot_instance: telebot.TeleBot) -> None:
    b = bot_instance

    @b.message_handler(content_types=["photo"])
    @catch_errors
    def _photo(m: types.Message) -> None:
        on_photo(m)

    @b.message_handler(content_types=["document"])
    @catch_errors
    def _doc(m: types.Message) -> None:
        on_document(m)

    @b.message_handler(func=lambda m: True, content_types=["text"])
    @catch_errors
    def _text(m: types.Message) -> None:
        on_text(m)


# ══════════════════════════════════════════════════════════════════════════════
#  CODING AGENT: SELF-CORRECTION
# ══════════════════════════════════════════════════════════════════════════════

MAX_ITERATIONS = 5


def _agent_project_root() -> Path:
    return Path(__file__).resolve().parent


def _agent_resolve(uid: int, path: str) -> Path:
    root = _agent_project_root().resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise BotError("Path traversal not allowed.")
    return target


def _agent_read(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise BotError(f"File not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="replace")


def _agent_naive_fix(code: str, findings: List[Dict[str, str]]) -> str:
    fixed = code
    for finding in findings:
        rule = finding.get("rule", "")
        if rule.startswith("call:"):
            name = rule.split(":", 1)[1]
            fixed = fixed.replace(name, f"# BLOCKED: {name}")
    return fixed


@catch_errors
def cmd_selfcorrect(message: types.Message) -> None:
    """/selfcorrect <path> — read, scan, fix, re-scan until safe."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, "Usage: <code>/selfcorrect path/to/file.py</code>")
        return
    path = parts[1].strip()
    target = _agent_resolve(uid, path)

    original = _agent_read(target)
    iterations: List[Dict[str, Any]] = []
    current = original

    for i in range(1, MAX_ITERATIONS + 1):
        result = scan_code(current, path)
        iterations.append(
            {
                "iteration": i,
                "verdict": result["verdict"],
                "risk_score": result["risk_score"],
                "findings": len(result["findings"]),
            }
        )
        if result["safe"]:
            break
        fixed = _agent_naive_fix(current, result["findings"])
        if fixed == current:
            iterations[-1]["note"] = "no fix applied"
            break
        current = fixed

    changed = current != original
    if changed:
        target.write_text(current, encoding="utf-8")
        store.audit(uid, "self_correct", path, f"iterations={len(iterations)}")

    rows = [
        [it["iteration"], it["verdict"], str(it["risk_score"]), str(it["findings"])]
        for it in iterations
    ]
    table = rich_table(["Iter", "Verdict", "Risk", "Findings"], rows,
                       title=f"🔄 Self-Correction: {esc_html(path)}", max_width=16)

    diff = ""
    if changed:
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(), current.splitlines(), lineterm="", n=2,
            )
        )
        if diff_lines:
            diff = "<pre>" + esc_html("\n".join(diff_lines[:40])) + "</pre>"

    text = (
        f"{table}\n"
        f"{G['bullet']} Changes applied: <b>{'yes' if changed else 'no'}</b>\n"
        f"{diff}"
    )
    send_text(message.chat.id, text)


# ══════════════════════════════════════════════════════════════════════════════
#  KEEP-ALIVE (Flask)
# ══════════════════════════════════════════════════════════════════════════════

def _start_keepalive() -> None:
    try:
        from flask import Flask

        app = Flask("coding_agent")

        @app.route("/health")
        def health():
            return {"ok": True, "bot": BRAND_TAG}, 200

        @app.route("/")
        def root():
            return f"{BRAND_TAG} online", 200

        thread = threading.Thread(
            target=lambda: app.run(host="0.0.0.0", port=KEEPALIVE_PORT),
            daemon=True, name="keepalive",
        )
        thread.start()
        log.info("keepalive http on port %s", KEEPALIVE_PORT)
    except Exception as exc:  # noqa: BLE001
        log.debug("keepalive not started: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN / ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def _set_commands(bot: telebot.TeleBot) -> None:
    cmds = [
        types.BotCommand("start", "Open main menu"),
        types.BotCommand("menu", "Main menu"),
        types.BotCommand("help", "Help & FAQ"),
        types.BotCommand("id", "Your user ID"),
        types.BotCommand("cancel", "Cancel current action"),
        types.BotCommand("ping", "Latency check"),
        types.BotCommand("code", "Read a project file"),
        types.BotCommand("read", "Read a project file"),
        types.BotCommand("write", "Write new content to a file"),
        types.BotCommand("exec", "Run a terminal command"),
        types.BotCommand("fix", "Auto-fix errors in a file"),
        types.BotCommand("review", "Review code quality"),
        types.BotCommand("selfcorrect", "Self-correct a file until safe"),
        types.BotCommand("stats", "Bot statistics"),
        types.BotCommand("ban", "Ban / unban a user"),
        types.BotCommand("broadcast", "Announce to all users"),
        types.BotCommand("admin", "Admin panel"),
    ]
    try:
        bot.set_my_commands(cmds)
        log.info("bot commands registered (%d)", len(cmds))
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to register bot commands: %s", exc)


def build_and_run() -> int:
    config = BotConfig()
    config.validate()

    log.info("=" * 60)
    log.info("   %s", BRAND_TAG)
    log.info("   owner id   : %s", OWNER_ID)
    log.info("   db         : %s", config.db_file)
    log.info("   rate limit : %s actions / %ss", RATE.max, RATE.window)
    log.info("   storage    : %s", "sqlite" if USE_SQLITE else "json")
    log.info("=" * 60)

    bot = telebot.TeleBot(config.token, parse_mode="HTML", threaded=True, num_threads=8)
    set_bot(bot)

    register_commands(bot)
    register_callbacks(bot)
    register_messages(bot)
    register_admin(bot)

    _set_commands(bot)

    try:
        users = store.load_all().get("users", {})
        bots = store.load_all().get("bots", {})
        notify_owner(
            f"<b>✅ Panel Online</b> — {BRAND_TAG}\n"
            f"{G['bullet']} Owner: <code>{OWNER_ID}</code>\n"
            f"{G['bullet']} Users: <b>{len(users)}</b>\n"
            f"{G['bullet']} Bots: <b>{len(bots)}</b>{footer()}"
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("owner notify skipped: %s", exc)

    try:
        bot.remove_webhook()
        try:
            bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        log.info("webhook cleared")
    except Exception as exc:  # noqa: BLE001
        log.warning("webhook clear warning: %s", exc)

    _start_keepalive()

    stop = threading.Event()

    def _handle_signal(signum, frame):  # noqa: ARG001
        log.info("signal %s received — stopping…", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log.info("polling…")
    while not stop.is_set():
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=25)
        except KeyboardInterrupt:
            log.info("stopping…")
            break
        except Exception as exc:  # noqa: BLE001
            log.error("poll error: %s", exc)
            traceback.print_exc()
            if stop.wait(5):
                break
    return 0


def main() -> int:
    try:
        return build_and_run()
    except Exception as exc:  # noqa: BLE001
        log.critical("fatal: %s", exc, exc_info=True)
        print(f"[x] fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP & RUN
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. Install dependencies:
#      python -m pip install --upgrade pip
#      pip install -r requirements.txt
#
# 2. Create a bot via @BotFather, get the token:
#      export BOT_TOKEN="123456:ABC-DEF..."
#      export OWNER_ID="YOUR_TELEGRAM_USER_ID"   # optional
#      export USE_SQLITE=1                        # optional: SQLite storage
#
# 3. Run:
#      python bot.py
#
# Commands: /start /help /menu /id /cancel /ping /code /read /write /exec
#           /fix /review /selfcorrect /stats /ban /broadcast /admin
#
