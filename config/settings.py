"""Coding Agent Telegram Bot configuration package.

This package holds all environment-driven configuration, path constants,
branding and glyph definitions used across the bot. ``bot.py`` imports from
here so the entry point stays free of hard-coded values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Final

# ──────────────────────────────────────────────────────────────────────
#  Filesystem layout
# ──────────────────────────────────────────────────────────────────────
ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DATA_DIR: Final[Path] = ROOT / "data"
BOTS_DIR: Final[Path] = DATA_DIR / "bots"
TMP_DIR: Final[Path] = DATA_DIR / "tmp"
KEYCACHE_DIR: Final[Path] = DATA_DIR / "keycache"
LOGS_DIR: Final[Path] = ROOT / "logs"

DB_FILE: Final[Path] = DATA_DIR / "panel_db.json"
SETTINGS_FILE: Final[Path] = DATA_DIR / "panel_settings.json"
AUDIT_FILE: Final[Path] = DATA_DIR / "audit.log"

for _p in (DATA_DIR, BOTS_DIR, TMP_DIR, KEYCACHE_DIR, LOGS_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────
#  Environment / secrets
# ──────────────────────────────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


# Bot token (set via BotFather). Precedence: BOT_TOKEN > MAIN_BOT_TOKEN >
# TELEGRAM_BOT_TOKEN. Falls back to a placeholder that must be replaced.
BOT_TOKEN: Final[str] = (
    _env_str("BOT_TOKEN")
    or _env_str("MAIN_BOT_TOKEN")
    or _env_str("TELEGRAM_BOT_TOKEN")
    or "BOT_TOKEN"
).strip()

try:
    OWNER_ID: Final[int] = int(_env_str("OWNER_ID", "0"))
except ValueError:
    OWNER_ID = 0

ANNOUNCE_CHANNEL: Final[str] = _env_str("ANNOUNCE_CHANNEL", "")
KEEPALIVE_PORT: Final[int] = _env_int("PORT", 10460)

GITHUB_TOKEN: Final[str] = _env_str("GITHUB_TOKEN", "")
GITHUB_KEY_REPO: Final[str] = _env_str("GITHUB_KEY_REPO", "")
GITHUB_REPO: Final[str] = _env_str("GITHUB_REPO", "")

# ──────────────────────────────────────────────────────────────────────
#  Branding
# ──────────────────────────────────────────────────────────────────────
BRAND: Final[str] = "\u0073\u0069\u006D\u0072\u0061\u006E \u0048\u006F\u0073\u0074\u0069\u006E\u0067 \u0043\u006F\u0064\u0069\u006E\u0067 \u0041\u0067\u0065\u006E\u0074"
BRAND_VER: Final[str] = "v3.0.0"
BRAND_TAG: Final[str] = f"{BRAND} {BRAND_VER}"
SUPPORT_USR: Final[str] = "@support"
FOOTER: Final[str] = f"\n\n<blockquote>{BRAND_TAG}</blockquote>"

# ──────────────────────────────────────────────────────────────────────
#  UI glyphs / symbols
# ──────────────────────────────────────────────────────────────────────
G: Final[Dict[str, str]] = {
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
    """Aggregated runtime configuration for the Coding Agent bot."""

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
    bots_dir: Path = BOTS_DIR
    tmp_dir: Path = TMP_DIR
    log_dir: Path = LOGS_DIR
    db_file: Path = DB_FILE
    settings_file: Path = SETTINGS_FILE
    audit_file: Path = AUDIT_FILE

    def is_owner(self, uid: int) -> bool:
        """Return True if ``uid`` is the configured owner."""
        return self.owner_id > 0 and uid == self.owner_id

    def validate(self) -> None:
        """Raise :class:`RuntimeError` if required config is missing."""
        if not self.token or self.token == "BOT_TOKEN":
            raise RuntimeError(
                "BOT_TOKEN is not set. Export BOT_TOKEN (from BotFather) "
                "and redeploy, e.g.:\n  export BOT_TOKEN=123456:ABC-DEF..."
            )
