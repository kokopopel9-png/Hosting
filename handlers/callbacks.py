"""Inline keyboard callback-query handler and router.

All ``callback_data`` actions are routed here. The router keeps a registry of
``prefix -> handler`` so new features can add callbacks without touching the
root handler.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Pattern

import telebot
from telebot import types

from handlers.base import get_bot, send_text
from utils.logging import catch_errors, log

# Registry: callback_data prefix (or exact match) -> handler(call, data)
CallbackHandler = Callable[[types.CallbackQuery, str], None]
_REGISTRY: Dict[str, CallbackHandler] = {}
_EXACT: Dict[str, CallbackHandler] = {}


def register_callback(prefix: str, handler: CallbackHandler) -> None:
    """Register a handler for callbacks whose data starts with ``prefix``."""
    _REGISTRY[prefix] = handler


def register_exact(data: str, handler: CallbackHandler) -> None:
    """Register a handler for an exact ``callback_data`` match."""
    _EXACT[data] = handler


def route_callback(call: types.CallbackQuery, data: str) -> None:
    """Route a callback to the matching registered handler."""
    # Exact match wins first.
    if data in _EXACT:
        _EXACT[data](call, data)
        return
    # Prefix match (longest prefix first).
    matched: Optional[str] = None
    for prefix in sorted(_REGISTRY, key=len, reverse=True):
        if data.startswith(prefix):
            matched = prefix
            break
    if matched is not None:
        _REGISTRY[matched](call, data)
        return
    # Fallback: echo back.
    b = get_bot()
    b.answer_callback_query(call.id, text="Unknown action.")


@catch_errors
def cb_root(call: types.CallbackQuery) -> None:
    """Root catch-all callback handler (registered on ``func=lambda c: True``)."""
    data = call.data or ""
    b = get_bot()
    try:
        b.answer_callback_query(call.id)
    except Exception:
        pass
    route_callback(call, data)


def register_callbacks(bot_instance: telebot.TeleBot) -> None:
    """Attach the root callback handler to ``bot_instance``."""
    b = bot_instance

    @b.callback_query_handler(func=lambda c: True)
    @catch_errors
    def _root(call: types.CallbackQuery) -> None:
        cb_root(call)
