"""Coding Agent Telegram Bot — entry point.

This module wires together the modular packages:

* :mod:`config` — settings, constants, glyphs
* :mod:`utils` — logging, storage, rate limiting, security, formatting, crypto
* :mod:`handlers` — commands, callbacks, messages, admin, agent

It builds the :class:`telebot.TeleBot`, registers every handler, and runs the
polling loop. Run with::

    python bot.py

Configuration is via environment variables (see :mod:`config.settings` and the
setup instructions at the bottom of this file).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback
from typing import Optional

import telebot
from telebot import types

from config.settings import ANNOUNCE_CHANNEL, BOT_TOKEN, BotConfig, BRAND_TAG, FOOTER, G, KEEPALIVE_PORT, OWNER_ID
from handlers.admin import register_admin
from handlers.agent import register_agent
from handlers.base import get_bot, notify_owner, set_bot
from handlers.callbacks import register_callbacks
from handlers.commands import register_commands
from handlers.messages import register_messages
from utils.logging import BotError, catch_errors, log, setup_logger
from utils.rate import RATE, maybe_auto_ban
from utils.storage import get_or_create_user, store

logger = setup_logger("coding_agent")

# ---------------------------------------------------------------------------
#  Background keep-alive (optional HTTP health endpoint for hosting platforms)
# ---------------------------------------------------------------------------
def _start_keepalive() -> None:
    """Start a tiny HTTP health server on KEEPALIVE_PORT (best effort)."""
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
            daemon=True,
            name="keepalive",
        )
        thread.start()
        logger.info("keepalive http on port %s", KEEPALIVE_PORT)
    except Exception as exc:  # flask may not be installed
        logger.debug("keepalive not started: %s", exc)


# ---------------------------------------------------------------------------
#  Bot command list
# ---------------------------------------------------------------------------
def _set_commands(bot: telebot.TeleBot) -> None:
    """Declare the public command list shown by Telegram clients."""
    cmds = [
        types.BotCommand("start", "Open main menu"),
        types.BotCommand("menu", "Main menu"),
        types.BotCommand("help", "Help & FAQ"),
        types.BotCommand("id", "Your user ID"),
        types.BotCommand("cancel", "Cancel current action"),
        types.BotCommand("ping", "Latency check"),
        # Coding agent.
        types.BotCommand("code", "Read a project file"),
        types.BotCommand("read", "Read a project file"),
        types.BotCommand("write", "Write new content to a file"),
        types.BotCommand("exec", "Run a terminal command"),
        types.BotCommand("fix", "Auto-fix errors in a file"),
        types.BotCommand("review", "Review code quality"),
        types.BotCommand("selfcorrect", "Self-correct a file until safe"),
        # Admin (owner only).
        types.BotCommand("stats", "Bot statistics"),
        types.BotCommand("ban", "Ban / unban a user"),
        types.BotCommand("broadcast", "Announce to all users"),
        types.BotCommand("admin", "Admin panel"),
    ]
    try:
        bot.set_my_commands(cmds)
        logger.info("bot commands registered (%d)", len(cmds))
    except Exception as exc:
        logger.warning("failed to register bot commands: %s", exc)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
def build_and_run() -> int:
    """Build the bot, register handlers, and enter the polling loop."""
    config = BotConfig()
    config.validate()

    # Logging banner.
    logger.info("=" * 60)
    logger.info("   %s", BRAND_TAG)
    logger.info("   owner id   : %s", OWNER_ID)
    logger.info("   db         : %s", config.db_file)
    logger.info("   rate limit : %s actions / %ss", RATE.max, RATE.window)
    logger.info("=" * 60)

    # Build bot instance.
    bot = telebot.TeleBot(config.token, parse_mode="HTML", threaded=True, num_threads=8)
    set_bot(bot)

    # Register all handler modules.
    register_commands(bot)
    register_callbacks(bot)
    register_messages(bot)
    register_admin(bot)
    register_agent(bot)

    # Public command menu.
    _set_commands(bot)

    # Notify owner on start.
    try:
        users = store.load_all().get("users", {})
        bots = store.load_all().get("bots", {})
        notify_owner(
            f"<b>✅ Panel Online</b> — {BRAND_TAG}\n"
            f"{G['bullet']} Owner: <code>{OWNER_ID}</code>\n"
            f"{G['bullet']} Users: <b>{len(users)}</b>\n"
            f"{G['bullet']} Bots: <b>{len(bots)}</b>\n"
            f"{FOOTER}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("owner notify skipped: %s", exc)

    # Clear any previous webhook so polling works cleanly.
    try:
        bot.remove_webhook()
        try:
            bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        logger.info("webhook cleared")
    except Exception as exc:
        logger.warning("webhook clear warning: %s", exc)

    # Start keep-alive (Flask) if available.
    _start_keepalive()

    # Graceful shutdown on SIGINT/SIGTERM.
    stop = threading.Event()

    def _handle_signal(signum, frame):  # noqa: ARG001
        logger.info("signal %s received — stopping…", signum)
        stop.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("polling…")
    while not stop.is_set():
        try:
            # infinity_polling blocks; poll with a long timeout so we can
            # honour stop events between updates.
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=25)
        except KeyboardInterrupt:
            logger.info("stopping…")
            break
        except Exception as exc:
            logger.error("poll error: %s", exc)
            traceback.print_exc()
            if stop.wait(5):
                break
    return 0


def main() -> int:
    """Entry point with top-level error handling."""
    try:
        return build_and_run()
    except BotError as exc:
        logger.error("config error: %s", exc)
        print(f"[x] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        logger.critical("fatal: %s", exc, exc_info=True)
        print(f"[x] fatal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP & RUN INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. Install Python (3.9+) and dependencies:
#
#      python -m pip install --upgrade pip
#      pip install -r requirements.txt
#
# 2. Create a bot with @BotFather and copy the token. Export it:
#
#      export BOT_TOKEN="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
#      export OWNER_ID="YOUR_TELEGRAM_USER_ID"   # optional; first /start user becomes owner
#
# 3. Run:
#
#      python bot.py
#
# 4. (Optional) Use SQLite for production storage instead of JSON:
#
#      export USE_SQLITE=1
#
# 5. Talk to your bot in Telegram: /start, /help, /code, /exec, /stats, /ban, /broadcast
#
# ═══════════════════════════════════════════════════════════════════════════════
#  MIGRATION CHANGES & FEATURES ADDED
# ═══════════════════════════════════════════════════════════════════════════════
#
# STRUCTURE (monolith -> modules, original preserved as bot_legacy.py):
#   config/settings.py   - env, paths, branding, glyphs, BotConfig dataclass
#   utils/logging.py     - rotating file+console logger, catch_errors decorator
#   utils/storage.py     - JSON (default) + SQLite user/bot data store
#   utils/rate.py        - sliding-window rate limiter + anti-spam + auto-ban
#   utils/security.py    - blocked-command patterns + static code scanner
#   utils/formatting.py  - esc, fmt_bytes, rich_table, progress_bar, chunk_text
#   utils/crypto.py      - Fernet file encryption + in-memory key ring
#   handlers/base.py     - TeleBot instance, owner/admin/banned decorators
#   handlers/commands.py - /start /help /menu /id /cancel /ping /admin
#   handlers/commands.py - coding agent: /code /read /write /exec /fix /review /selfcorrect
#   handlers/commands.py - admin: /stats /ban /broadcast
#   handlers/callbacks.py - prefix/exact callback router
#   handlers/messages.py - photo / document / text handlers
#   handlers/admin.py    - inline admin panel (stats, broadcast, ban/unban)
#   handlers/agent.py    - self-correction loop (read -> scan -> fix -> rescan)
#   bot.py               - entry point; imports modules and runs polling
#
# FEATURES ADDED / ENHANCED:
#   ✅ Type hints + docstrings on all public functions/classes
#   ✅ Centralised logging (console + rotating file logs/bot.log)
#   ✅ Structured error handling (catch_errors decorator, BotError/SecurityError)
#   ✅ Rate limiting / anti-spam with sliding windows + auto-ban escalation
#   ✅ User data persistence (JSON default; SQLite via USE_SQLITE=1)
#   ✅ Admin commands: /stats, /broadcast, /ban (inline panel too)
#   ✅ Inline keyboards + callback query handler with prefix/exact routing
#   ✅ Coding Agent commands: /code /read /write /exec /fix /review /selfcorrect
#   ✅ Self-correction loop (read, static scan, fix, re-scan up to N iterations)
#   ✅ Security watchdog: blocks destructive/dangerous terminal commands
#   ✅ Path-traversal protection for file read/write
#   ✅ Rich tables (HTML <pre> aligned + HTML <table> fallback)
#   ✅ Bot API 9.4 button-style ready, graceful shutdown (SIGINT/SIGTERM)
#   ✅ Original monolith preserved at bot_legacy.py (no code deleted)
#
# NOTE: pyTelegramBotAPI does not expose a native "RichMessage/Rich Table"
# Telegram type; rich output is rendered as HTML tables / <pre> blocks and the
# Btn.style (Bot API 9.4) approach is retained for inline buttons.
