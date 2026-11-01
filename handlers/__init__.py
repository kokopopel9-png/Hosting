"""Handler package for the Coding Agent Telegram Bot."""

from __future__ import annotations

from .admin import register_admin  # noqa: F401
from .agent import register_agent  # noqa: F401
from .callbacks import register_callbacks, route_callback  # noqa: F401
from .commands import register_commands, cmd_admin  # noqa: F401
from .messages import register_messages  # noqa: F401

__all__ = [
    "register_admin",
    "register_agent",
    "register_callbacks",
    "route_callback",
    "register_commands",
    "cmd_admin",
    "register_messages",
]
