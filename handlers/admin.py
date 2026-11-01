"""Admin panel handlers (inline callbacks for /stats, /broadcast, /ban, etc.)."""

from __future__ import annotations

from typing import Any

import telebot
from telebot import types

from handlers.base import admin_or_owner, get_bot, send_text
from handlers.callbacks import register_callback, register_exact
from utils.formatting import rich_table
from utils.logging import catch_errors
from utils.storage import store


@admin_or_owner
def adm_stats(call: types.CallbackQuery, data: str) -> None:
    """Show admin statistics dashboard."""
    d = store.load_all()
    users = d.get("users", {})
    bots = d.get("bots", {})
    running = sum(1 for b in bots.values() if b.get("status") == "running")
    banned = sum(1 for v in d.get("banned", {}).values() if v)
    rows = [
        ["Users", str(len(users))],
        ["Banned", str(banned)],
        ["Bots", str(len(bots))],
        ["Running", str(running)],
        ["Owner", str(call.from_user.id)],
    ]
    text = rich_table(
        ["Metric", "Value"],
        rows,
        title="📊 Admin Statistics",
        max_width=24,
    )
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        text + "\n" + _footer(),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=_back_kb("menu_admin"),
    )


@admin_or_owner
def adm_broadcast(call: types.CallbackQuery, data: str) -> None:
    """Prompt the admin to enter broadcast text."""
    uid = call.from_user.id
    store.upsert_user(uid, {"pending_action": "broadcast"})
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        "📢 Send the broadcast message now (text only).\n"
        "It will be delivered to all non-banned users."
        + _footer(),
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=_back_kb("menu_admin"),
    )


@admin_or_owner
def adm_ban(call: types.CallbackQuery, data: str) -> None:
    """List banned users with unban buttons."""
    d = store.load_all()
    banned = {k: v for k, v in d.get("banned", {}).items() if v}
    if not banned:
        text = "🚫 No banned users." + _footer()
        kb = _back_kb("menu_admin")
    else:
        rows = [[uid, "⛓ Banned"] for uid in banned]
        text = rich_table(
            ["User ID", "Status"],
            rows,
            title="🚫 Banned Users",
            max_width=16,
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        for uid in list(banned)[:10]:
            kb.add(types.InlineKeyboardButton(f"Unban {uid}", callback_data=f"adm_unban_{uid}"))
        kb.add(types.InlineKeyboardButton("↲ Back", callback_data="menu_admin"))
    b = get_bot()
    b.answer_callback_query(call.id)
    b.edit_message_text(
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=kb,
    )


def adm_unban(call: types.CallbackQuery, data: str) -> None:
    """Unban a user (callback data: adm_unban_<uid>)."""
    try:
        target = int(data.split("_")[-1])
    except ValueError:
        return
    from utils.storage import store as _store

    _store.set_banned(target, False)
    _store.audit(call.from_user.id, "adm_unban", str(target))
    b = get_bot()
    b.answer_callback_query(call.id, text=f"Unbanned {target}")
    # Re-render the ban list.
    adm_ban(call, "adm_ban")


def _back_kb(target: str) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("↲ Back", callback_data=target))
    return kb


def _footer() -> str:
    from config.settings import FOOTER

    return FOOTER


def register_admin(bot_instance: telebot.TeleBot) -> None:
    """Register admin callback handlers on ``bot_instance``."""
    register_exact("adm_stats", adm_stats)
    register_exact("adm_broadcast", adm_broadcast)
    register_exact("adm_ban", adm_ban)
    register_callback("adm_unban_", adm_unban)
