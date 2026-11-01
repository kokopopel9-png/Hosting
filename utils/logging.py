"""Logging and structured error handling for the Coding Agent bot.

Provides a module-level :class:`logging.Logger`, a console + file handler
setup, and a reusable :func:`catch_errors` decorator that logs exceptions,
notifies the owner (when a bot instance is available), and prevents a single
handler failure from killing the polling loop.
"""

from __future__ import annotations

import functools
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from config.settings import LOGS_DIR

FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

_T = TypeVar("_T")
Func = Callable[..., _T]


def setup_logger(name: str = "coding_agent", level: int = logging.INFO) -> logging.Logger:
    """Configure and return a logger writing to console and ``logs/bot.log``.

    The logger rotates the log file at 5 MB and keeps 3 backups so the disk
    does not fill up during long-running deployments.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        # Already configured (e.g. reloaded in tests).
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)

    # Console handler.
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(level)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    # Rotating file handler.
    try:
        fh = logging.handlers.RotatingFileHandler(
            LOGS_DIR / "bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except OSError:
        # Logging to disk is optional; console still works.
        pass

    return logger


log = setup_logger()


class BotError(Exception):
    """Raised for recoverable bot-level failures (e.g. bad input, missing file)."""


class SecurityError(Exception):
    """Raised when a command/action is blocked by the security watchdog."""


def catch_errors(
    func: Func,
    *,
    notify_owner: bool = False,
    reraise: bool = False,
    default_return: Any = None,
) -> Func:
    """Decorator: catch exceptions, log them, optionally notify the owner.

    Parameters
    ----------
    notify_owner:
        If True and the wrapped callable receives a ``bot`` keyword/positional
        argument that exposes ``send_message``, a brief error summary is sent
        to the configured owner.
    reraise:
        If True the exception is re-raised after logging (default swallows).
    default_return:
        Value returned when an exception is caught and not re-raised.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - we log and continue
            tb = traceback.format_exc()
            log.error("Error in %s: %s\n%s", func.__qualname__, exc, tb)
            if notify_owner:
                _notify_owner_error(func.__qualname__, exc, args, kwargs)
            if reraise:
                raise
            return default_return

    return wrapper  # type: ignore[return-value]


def _notify_owner_error(
    where: str, exc: BaseException, args: tuple, kwargs: dict
) -> None:
    """Best-effort owner notification for a handled exception."""
    from config.settings import OWNER_ID  # imported lazily to avoid cycles

    bot = None
    for arg in (*args, *kwargs.values()):
        if hasattr(arg, "send_message"):
            bot = arg
            break
    if bot is None or OWNER_ID <= 0:
        return
    try:
        bot.send_message(
            OWNER_ID,
            (
                f"<b>⚠ Handler error</b>\n"
                f"<b>Func:</b> <code>{where}</code>\n"
                f"<b>Error:</b> <code>{esc_html(str(exc))}</code>"
            ),
            parse_mode="HTML",
        )
    except Exception:  # noqa: BLE001 - never let notification crash the bot
        log.debug("Failed to notify owner of error", exc_info=True)


def esc_html(text: str) -> str:
    """Escape a string for safe inclusion in Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
