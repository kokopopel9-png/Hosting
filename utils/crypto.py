"""File encryption helpers (Fernet symmetric encryption).

Preserves the legacy behaviour: every uploaded user file is encrypted with a
unique Fernet key; keys are held in memory (and optionally mirrored to a
private GitHub key repo). Local disk stores only ciphertext.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.fernet import Fernet

from config.settings import KEYCACHE_DIR

KEYCACHE_DIR.mkdir(parents=True, exist_ok=True)


class KeyRing:
    """In-memory encryption key store with an encrypted local disk cache."""

    def __init__(self) -> None:
        self._mem: Dict[str, bytes] = {}
        self._lock = threading.Lock()

    # -- public API -----------------------------------------------------
    def new_key(self) -> bytes:
        return Fernet.generate_key()

    def store(self, key_id: str, key: bytes, meta: Dict[str, Any]) -> bool:
        """Cache key in memory and write an encrypted local copy."""
        with self._lock:
            self._mem[key_id] = key
        try:
            self._cache_local(key_id, key)
        except Exception:
            pass
        return True

    def fetch(self, key_id: str) -> Optional[bytes]:
        with self._lock:
            cached = self._mem.get(key_id)
        if cached:
            return cached
        return self._uncache_local(key_id)

    def wipe(self, key_id: str) -> None:
        with self._lock:
            self._mem.pop(key_id, None)

    def remove(self, key_id: str) -> None:
        self.wipe(key_id)
        try:
            (KEYCACHE_DIR / f"{key_id}.bin").unlink(missing_ok=True)  # type: ignore[arg-type]
        except OSError:
            pass

    # -- local encrypted cache ------------------------------------------
    def _local_master(self) -> bytes:
        # Derived at runtime from bot token + owner id (never stored plain).
        from config.settings import BOT_TOKEN, OWNER_ID

        material = f"{BOT_TOKEN}|{OWNER_ID}".encode()
        digest = hashlib.sha256(material).digest()
        return base64.urlsafe_b64encode(digest)

    def _cache_local(self, key_id: str, key: bytes) -> None:
        f = Fernet(self._local_master())
        (KEYCACHE_DIR / f"{key_id}.bin").write_bytes(f.encrypt(key))

    def _uncache_local(self, key_id: str) -> Optional[bytes]:
        p = KEYCACHE_DIR / f"{key_id}.bin"
        if not p.exists():
            return None
        try:
            f = Fernet(self._local_master())
            key = f.decrypt(p.read_bytes())
            with self._lock:
                self._mem[key_id] = key
            return key
        except Exception:
            return None


KEYRING = KeyRing()


def encrypt_file(plain: bytes) -> Tuple[str, bytes, bytes]:
    """Encrypt ``plain`` and return ``(key_id, key, ciphertext)``."""
    key = KEYRING.new_key()
    cipher = Fernet(key).encrypt(plain)
    key_id = secrets.token_urlsafe(16)
    return key_id, key, cipher


def decrypt_with(key: bytes, cipher: bytes) -> bytes:
    return Fernet(key).decrypt(cipher)


def write_encrypted(path: Path, key: bytes, plain: bytes) -> None:
    path.write_bytes(Fernet(key).encrypt(plain))


def read_encrypted(path: Path, key: bytes) -> bytes:
    return Fernet(key).decrypt(path.read_bytes())
