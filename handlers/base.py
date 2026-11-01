"""Shared handler foundation: bot instance, access decorators and helpers.

All handler modules import the configured :class:`telebot.TeleBot` from here
so there is a single source of truth for the API client.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional

import telebot
from telebot import types

from config.settings import BRAND_TAG, FOOTER, OWNER_ID, G
from utils.logging import BotError, catch_errors, esc_html, log
from utils.rate import COMMAND_RATE, RATE, RateLimiter, rate_limited
from utils.storage import get_or_create_user, is_banned, maybe_auto_ban, store

# ---------------------------------------------------------------------------
#  Bot instance
# ---------------------------------------------------------------------------
def build_bot(token: str, parse_mode: str = "HTML") -> telebot.TeleBot:
    """Build and return a threaded :class:`telebot.TeleBot` instance."""
    return telebot.TeleBot(token, parse_mode=parse_mode, threaded=True, num_threads=8)


# Created by :func:`bot.main` once the token is validated.
bot: Optional[telebot.TeleBot] = None


def set_bot(instance: telebot.TeleBot) -> None:
    global bot
    bot = instance


def get_bot() -> telebot.TeleBot:
    if bot is None:
        raise RuntimeError("TeleBot instance not initialized; call set_bot() first.")
    return bot


# ---------------------------------------------------------------------------
#  Access-control decorators
# ---------------------------------------------------------------------------
F = Callable[..., Any]


def owner_only(func: F) -> F:
    """Restrict a handler to the bot owner."""

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
    """Restrict a handler to the owner or a stored admin user."""

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
    """Reject the call if the user is banned."""

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


def _extract_message(args: tuple, kwargs: dict) -> Optional[types.Message]:
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, types.Message):
            return arg
    for arg in (*args, *kwargs.values()):
        if isinstance(arg, types.CallbackQuery):
            return arg.message
    return None


# ---------------------------------------------------------------------------
#  Messaging helpers
# ---------------------------------------------------------------------------
def send_text(
    chat_id: int,
    text: str,
    *,
    reply_markup: Optional[types.InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
) -> Any:
    """Send a text message with centralized error handling."""
    b = get_bot()
    return b.send_message(
        chat_id,
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


def notify_owner(text: str) -> None:
    """Best-effort notification to the bot owner."""
    if OWNER_ID <= 0:
        return
    try:
        send_text(OWNER_ID, text)
    except Exception as exc:  # noqa: BLE001 - never crash on notification
        log.debug("Owner notification failed: %s", exc)


def footer() -> str:
    return FOOTER


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def now_ts() -> float:
    return time.time()
