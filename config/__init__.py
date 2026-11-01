"""Coding Agent Telegram Bot configuration package."""

from __future__ import annotations

from .settings import (  # noqa: F401
    BRAND,
    BRAND_TAG,
    BRAND_VER,
    DATA_DIR,
    DB_FILE,
    FOOTER,
    G,
    GITHUB_KEY_REPO,
    GITHUB_REPO,
    GITHUB_TOKEN,
    KEEPALIVE_PORT,
    OWNER_ID,
    ROOT,
    SUPPORT_USR,
    TMP_DIR,
    BotConfig,
    BOT_TOKEN,
)

__all__ = [
    "BOT_TOKEN",
    "OWNER_ID",
    "ANNOUNCE_CHANNEL",
    "KEEPALIVE_PORT",
    "GITHUB_TOKEN",
    "GITHUB_KEY_REPO",
    "GITHUB_REPO",
    "BRAND",
    "BRAND_VER",
    "BRAND_TAG",
    "SUPPORT_USR",
    "FOOTER",
    "G",
    "ROOT",
    "DATA_DIR",
    "DB_FILE",
    "TMP_DIR",
    "BotConfig",
]
