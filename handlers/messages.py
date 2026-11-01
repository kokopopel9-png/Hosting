"""Content message handlers (photo, document, free text)."""

from __future__ import annotations

import telebot
from telebot import types

from handlers.base import get_bot, send_text
from utils.logging import catch_errors
from utils.storage import get_or_create_user, store


@catch_errors
def on_photo(message: types.Message) -> None:
    """Handle uploaded photos (e.g. payment proofs, screenshots)."""
    uid = message.from_user.id
    user = get_or_create_user(uid)
    file_id = message.photo[-1].file_id if message.photo else None
    store.upsert_user(
        uid, {"last_photo_file_id": file_id, "last_action": "photo_upload"}
    )
    store.audit(uid, "photo_upload", str(file_id))
    send_text(
        message.chat.id,
        "🖼 Photo received. Use the relevant menu action to attach it."
        + _footer(),
    )


@catch_errors
def on_document(message: types.Message) -> None:
    """Handle uploaded documents (source files, configs, proofs)."""
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
        f"📄 Document received: <code>{file_name}</code>\n"
        f"Use /write <i>path</i> to apply it, or attach it to a bot upload."
        + _footer(),
    )


@catch_errors
def on_text(message: types.Message) -> None:
    """Handle free text (e.g. content for /write, coupon codes, tickets)."""
    uid = message.from_user.id
    user = store.get_user(uid) or {}
    pending = user.get("pending_action")
    path = user.get("pending_path")

    if pending == "write" and path:
        # Treat the message text as new file content.
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        target = (root / path).resolve()
        try:
            target.write_text(message.text, encoding="utf-8")
            store.upsert_user(uid, {"pending_action": None, "pending_path": None})
            store.audit(uid, "file_write", path)
            send_text(
                message.chat.id,
                f"✅ Wrote <code>{path}</code> ({len(message.text)} chars)." + _footer(),
            )
        except Exception as exc:  # noqa: BLE001
            send_text(
                message.chat.id, f"❌ Write failed: {exc}" + _footer()
            )
        return

    # No pending action: show a short hint.
    send_text(
        message.chat.id,
        "💬 Use /menu to open the main panel, or /help for commands."
        + _footer(),
    )


def _footer() -> str:
    from config.settings import FOOTER

    return FOOTER


def register_messages(bot_instance: telebot.TeleBot) -> None:
    """Attach content-type handlers to ``bot_instance``."""
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
        # Let command handlers run first; this catches non-command text.
        on_text(m)
