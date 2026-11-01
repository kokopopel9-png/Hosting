"""Utility package: logging, storage, rate limiting, security, formatting, crypto."""

from __future__ import annotations

from utils.crypto import KEYRING, decrypt_with, encrypt_file, read_encrypted, write_encrypted  # noqa: F401
from utils.formatting import esc, esc_md, fmt_bytes, fmt_dur, progress_bar, rich_table  # noqa: F401
from utils.logging import BotError, SecurityError, catch_errors, esc_html, log, setup_logger  # noqa: F401
from utils.rate import COMMAND_RATE, RATE, UPLOAD_RATE, RateLimiter, maybe_auto_ban, rate_limited  # noqa: F401
from utils.security import is_blocked_command, is_dangerous_code, scan_code  # noqa: F401
from utils.storage import (  # noqa: F401
    JsonStore,
    SqliteStore,
    db_load,
    db_save,
    get_or_create_user,
    get_store,
    store,
)

__all__ = [
    "KEYRING",
    "decrypt_with",
    "encrypt_file",
    "read_encrypted",
    "write_encrypted",
    "esc",
    "esc_md",
    "fmt_bytes",
    "fmt_dur",
    "progress_bar",
    "rich_table",
    "BotError",
    "SecurityError",
    "catch_errors",
    "esc_html",
    "log",
    "setup_logger",
    "COMMAND_RATE",
    "RATE",
    "UPLOAD_RATE",
    "RateLimiter",
    "maybe_auto_ban",
    "rate_limited",
    "is_blocked_command",
    "is_dangerous_code",
    "scan_code",
    "JsonStore",
    "SqliteStore",
    "db_load",
    "db_save",
    "get_or_create_user",
    "get_store",
    "store",
]
