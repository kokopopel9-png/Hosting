"""Rate limiting and anti-spam guards.

Provides a token-bucket-style :class:`RateLimiter` plus convenience instances
and a :func:`rate_limited` decorator for handlers. Repeated violations can be
escalated to an auto-ban via :func:`maybe_auto_ban`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Dict, Deque, Optional

from config.settings import OWNER_ID
from utils.storage import store

F = Callable[..., Any]


class RateLimiter:
    """Sliding-window rate limiter.

    ``allow(uid)`` returns ``True`` while the user has stayed under
    ``max_actions`` within the last ``window_s`` seconds.
    """

    def __init__(self, max_actions: int = 30, window_s: int = 60) -> None:
        self.max = max_actions
        self.window = window_s
        self._bucket: Dict[int, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, uid: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._bucket[uid]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max:
                return False
            q.append(now)
            return True

    def hits(self, uid: int) -> int:
        with self._lock:
            return len(self._bucket.get(uid, []))

    def reset(self, uid: Optional[int] = None) -> None:
        with self._lock:
            if uid is None:
                self._bucket.clear()
            else:
                self._bucket.pop(uid, None)


# Global limiters.
RATE = RateLimiter(max_actions=40, window_s=60)        # general commands
UPLOAD_RATE = RateLimiter(max_actions=8, window_s=300)  # file uploads
COMMAND_RATE = RateLimiter(max_actions=20, window_s=60)  # admin commands

# Tracks how many times a user has been rate-limited (for auto-ban).
_violation_counts: Dict[int, int] = {}
_violation_lock = threading.Lock()


def rate_limited(
    limiter: RateLimiter,
    *,
    message: str = "🚫 Too many requests. Please slow down and try again later.",
) -> Callable[[F], F]:
    """Decorator that rejects a call when the caller is rate-limited.

    The wrapped callable must receive the user id as the first positional
    argument or via the ``uid`` keyword.
    """

    def decorator(func: F) -> F:
        def _get_uid(args: tuple, kwargs: dict) -> Optional[int]:
            if "uid" in kwargs:
                return kwargs["uid"]  # type: ignore[return-value]
            for arg in args:
                if isinstance(arg, int):
                    return arg
            return None

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            uid = _get_uid(args, kwargs)
            if uid is not None and not limiter.allow(uid):
                with _violation_lock:
                    _violation_counts[uid] = _violation_counts.get(uid, 0) + 1
                return message  # caller decides how to surface this
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def maybe_auto_ban(uid: int, reason: str, threshold: int = 5) -> bool:
    """If a user repeatedly trips guards, auto-ban and notify the owner.

    Returns True when the user was (auto-)banned by this call.
    """
    with _violation_lock:
        count = _violation_counts.get(uid, 0) + 1
        _violation_counts[uid] = count

    if count >= threshold:
        store.set_banned(uid, True)
        store.audit(uid, "auto_ban", reason)
        return True
    return False
