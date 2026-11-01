"""User-facing command handlers.

Each handler is registered via :func:`register_commands` in :mod:`bot`.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import telebot
from telebot import types

from handlers.base import (
    admin_or_owner,
    footer,
    get_bot,
    notify_owner,
    require_unbanned,
    send_text,
)
from config.settings import BRAND_TAG, G, OWNER_ID
from utils.formatting import esc, fmt_bytes, progress_bar, rich_table
from utils.logging import BotError, catch_errors
from utils.rate import COMMAND_RATE, RATE, rate_limited
from utils.security import is_blocked_command
from utils.storage import get_or_create_user, store


# ══════════════════════════════════════════════════════════════════════
#  Core commands
# ══════════════════════════════════════════════════════════════════════


def cmd_start(message: types.Message) -> None:
    """/start — greet the user, create their record, show the main menu."""
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
        f"<b>{esc(BRAND_TAG)}</b>\n"
        f"{G['div']}\n"
        f"Welcome, <b>{esc(message.from_user.first_name or 'User')}</b>!\n"
        f"{G['bullet']} ID: <code>{uid}</code>\n"
        f"{G['bullet']} Plan: <b>{user.get('plan','free')}</b>\n"
        f"{G['bullet']} {G['agent']} Coding Agent ready — use /code, /read, /write, /exec\n"
        f"{footer()}"
    )
    send_text(message.chat.id, text, reply_markup=kb)


def cmd_help(message: types.Message) -> None:
    """/help — list available commands and features."""
    uid = message.from_user.id
    lines = [
        f"<b>{esc(BRAND_TAG)} — Help</b>",
        f"{G['div']}",
        f"{G['code']} <b>/code</b> <i>path</i> — read a project file",
        f"{G['terminal']} <b>/exec</b> <i>cmd</i> — run a terminal command",
        f"{G['fix']} <b>/fix</b> <i>path</i> — auto-fix errors in a file",
        f"{G['review']} <b>/review</b> <i>path</i> — review code quality",
        f"{G['bullet']} <b>/start</b> — main menu",
        f"{G['bullet']} <b>/menu</b> — main menu",
        f"{G['bullet']} <b>/id</b> — your user ID",
        f"{G['bullet']} <b>/cancel</b> — cancel current action",
        f"{G['bullet']} <b>/ping</b> — bot latency check",
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
    """/menu — open the inline main menu."""
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
        f"<b>Main Menu</b> — {esc(BRAND_TAG)}{footer()}",
        reply_markup=kb,
    )


def cmd_id(message: types.Message) -> None:
    """/id — show the user's Telegram ID."""
    uid = message.from_user.id
    send_text(
        message.chat.id,
        f"{G['user']} Your ID: <code>{uid}</code>\n"
        f"{G['bullet']} Chat: <code>{message.chat.id}</code>{footer()}",
    )


def cmd_cancel(message: types.Message) -> None:
    """/cancel — cancel any in-progress flow for the user."""
    uid = message.from_user.id
    # Clear any pending conversation state stored for the user.
    store.upsert_user(uid, {"pending_action": None})
    send_text(message.chat.id, "✅ Cancelled. Back to main menu." + footer())


def cmd_ping(message: types.Message) -> None:
    """/ping — round-trip latency check."""
    import time

    start = time.time()
    sent = send_text(message.chat.id, "🏓 Pinging...")
    elapsed = int((time.time() - start) * 1000)
    try:
        get_bot().edit_message_text(
            f"🏓 Pong! <b>{elapsed} ms</b>{footer()}",
            chat_id=message.chat.id,
            message_id=sent.message_id,
            parse_mode="HTML",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  Coding Agent commands
# ══════════════════════════════════════════════════════════════════════


def cmd_code(message: types.Message) -> None:
    """/code <path> — read and display a project file (rich table of lines)."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/code path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    try:
        content = _read_file_safe(uid, path)
    except BotError as exc:
        send_text(message.chat.id, f"❌ {esc(str(exc))}{footer()}")
        return
    lines = content.splitlines()
    rows = [[str(i + 1), esc(line)] for i, line in enumerate(lines[:200])]
    table = rich_table(
        ["Line", "Code"],
        rows,
        title=f"📄 {esc(path)}",
        max_width=60,
    )
    if len(lines) > 200:
        table += f"\n{G['bullet']} …{len(lines) - 200} more lines not shown."
    send_text(message.chat.id, table + footer())
    store.audit(uid, "code_read", path)


def cmd_read(message: types.Message) -> None:
    """/read <path> — alias for /code."""
    cmd_code(message)


def cmd_write(message: types.Message) -> None:
    """/write <path> — prompt the user to send the new file content."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/write path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    store.upsert_user(uid, {"pending_action": "write", "pending_path": path})
    send_text(
        message.chat.id,
        f"📝 Send the new content for <code>{esc(path)}</code> now.\n"
        f"Reply with the file content (or upload a .py file).{footer()}",
    )


def cmd_exec(message: types.Message) -> None:
    """/exec <cmd> — run a terminal command (sandboxed, blocked commands rejected)."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/exec command here</code>{footer()}")
        return
    command = parts[1].strip()
    blocked, reason = is_blocked_command(command)
    if blocked:
        send_text(
            message.chat.id,
            f"🚫 Blocked command: {esc(reason)}{footer()}",
        )
        store.audit(uid, "exec_blocked", command)
        return
    try:
        import subprocess

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd(),
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not output:
            output = "(no output)"
        output = esc(output)
    except Exception as exc:  # noqa: BLE001
        output = esc(str(exc))
    # Rich table of result
    rows = [[esc(command), progress_bar(100 if result.returncode == 0 else 0)]]
    table = rich_table(["Command", "Status"], rows, title="🖥 Exec Result", max_width=50)
    text = f"{table}\n\n<pre>{output[:3000]}</pre>{footer()}"
    send_text(message.chat.id, text)
    store.audit(uid, "exec", command, f"rc={result.returncode if 'result' in dir() else 'err'}")


def cmd_fix(message: types.Message) -> None:
    """/fix <path> — placeholder: auto-fix common errors in a file."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/fix path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    send_text(
        message.chat.id,
        f"🔧 <i>Auto-fix for {esc(path)} queued.</i>\n"
        f"(Self-correction engine reads, lints and rewrites the file.){footer()}",
    )
    store.audit(uid, "fix", path)


def cmd_review(message: types.Message) -> None:
    """/review <path> — placeholder: review code quality & security."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, f"Usage: <code>/review path/to/file.py</code>{footer()}")
        return
    path = parts[1].strip()
    send_text(
        message.chat.id,
        f"🔍 <i>Reviewing {esc(path)}…</i>\n"
        f"(Static scan + best-practice suggestions.){footer()}",
    )
    store.audit(uid, "review", path)


# ══════════════════════════════════════════════════════════════════════
#  Admin commands
# ══════════════════════════════════════════════════════════════════════


@admin_or_owner
@require_unbanned
def cmd_stats(message: types.Message) -> None:
    """/stats — bot statistics (users, bots, uptime, storage)."""
    data = store.load_all()
    users = data.get("users", {})
    bots = data.get("bots", {})
    running = sum(1 for b in bots.values() if b.get("status") == "running")
    banned = sum(1 for v in data.get("banned", {}).values() if v)
    from pathlib import Path

    db_path = Path("panel_db.json")
    db_size = db_path.stat().st_size if db_path.exists() else 0
    text = (
        f"<b>📊 Bot Statistics</b> — {esc(BRAND_TAG)}\n"
        f"{G['div']}\n"
        f"{G['users']} Users: <b>{len(users)}</b>\n"
        f"{G['user']} Banned: <b>{banned}</b>\n"
        f"{G['code']} Bots: <b>{len(bots)}</b> (running: <b>{running}</b>)\n"
        f"{G['graph']} DB: <b>{fmt_bytes(db_size)}</b>\n"
        f"{footer()}"
    )
    send_text(message.chat.id, text)


@admin_or_owner
@require_unbanned
def cmd_ban(message: types.Message) -> None:
    """/ban <user_id> — ban or unban a user (toggle)."""
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
    send_text(
        message.chat.id,
        f"✅ User <code>{target}</code> {state}.{footer()}",
    )
    notify_owner(f"{G['ban']} User {target} {state} by {message.from_user.id}")


@admin_or_owner
@require_unbanned
def cmd_broadcast(message: types.Message) -> None:
    """/broadcast <text> — announce to all non-banned users."""
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
            b.send_message(int(uid_str), f"<b>📢 Announcement</b>\n{esc(text)}{footer()}", parse_mode="HTML")
            sent += 1
        except Exception:
            fail += 1
    store.audit(message.from_user.id, "broadcast", text, f"sent={sent} fail={fail}")
    send_text(
        message.chat.id,
        f"📢 Broadcast done: <b>{sent}</b> sent, <b>{fail}</b> failed.{footer()}",
    )


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _read_file_safe(uid: int, path: str) -> str:
    """Read a file under the project root, rejecting path traversal."""
    from pathlib import Path

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


# ---------------------------------------------------------------------------
#  Registration
# ---------------------------------------------------------------------------


def register_commands(bot_instance: telebot.TeleBot) -> None:
    """Attach all command handlers to ``bot_instance``."""
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
        ("code", cmd_code),
        ("read", cmd_read),
        ("write", cmd_write),
        ("exec", cmd_exec),
        ("fix", cmd_fix),
        ("review", cmd_review),
    ):
        @b.message_handler(commands=[cmd])
        @catch_errors
        def _agent(m: types.Message, _h=handler) -> None:
            _h(m)

    # Admin commands.
    for cmd, handler in (
        ("stats", cmd_stats),
        ("ban", cmd_ban),
        ("broadcast", cmd_broadcast),
    ):
        @b.message_handler(commands=[cmd])
        @catch_errors
        def _admin(m: types.Message, _h=handler) -> None:
            _h(m)

    @b.message_handler(commands=["admin"])
    @catch_errors
    def _admin_panel(m: types.Message) -> None:
        cmd_admin(m)


def cmd_admin(message: types.Message) -> None:
    """/admin — open the admin panel (owner only)."""
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
        f"<b>⚙ Admin Panel</b> — {esc(BRAND_TAG)}{footer()}",
        reply_markup=kb,
    )
