"""Coding Agent capabilities: self-correction loop and subagent simulation.

Implements the agent loop described by the user:

1. **Read** a file.
2. **Scan** it statically (security + syntax).
3. **Rewrite / fix** if issues are found.
4. **Re-scan** until safe or a max iteration cap is reached (self-correction).
5. Report a diff-style summary to the user.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List

import telebot
from telebot import types

from handlers.base import send_text
from utils.formatting import esc, rich_table
from utils.logging import BotError, catch_errors
from utils.security import scan_code
from utils.storage import store
from config.settings import G

MAX_ITERATIONS = 5


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve(uid: int, path: str) -> Path:
    root = _project_root().resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise BotError("Path traversal not allowed.")
    return target


def _read(path: Path) -> str:
    if not path.exists() or not path.is_file():
        raise BotError(f"File not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("utf-8", errors="replace")


def _naive_fix(code: str, findings: List[Dict[str, str]]) -> str:
    """Best-effort deterministic neutralisation of flagged dangerous calls."""
    fixed = code
    for finding in findings:
        rule = finding.get("rule", "")
        if rule.startswith("call:"):
            name = rule.split(":", 1)[1]
            fixed = fixed.replace(name, f"# BLOCKED: {name}")
    return fixed


@catch_errors
def agent_self_correct(message: types.Message) -> None:
    """/selfcorrect <path> — read, scan, fix, re-scan until safe."""
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        send_text(message.chat.id, "Usage: <code>/selfcorrect path/to/file.py</code>")
        return
    path = parts[1].strip()
    target = _resolve(uid, path)

    original = _read(target)
    iterations: List[Dict[str, Any]] = []
    current = original

    for i in range(1, MAX_ITERATIONS + 1):
        result = scan_code(current, path)
        iterations.append(
            {
                "iteration": i,
                "verdict": result["verdict"],
                "risk_score": result["risk_score"],
                "findings": len(result["findings"]),
            }
        )
        if result["safe"]:
            break
        fixed = _naive_fix(current, result["findings"])
        if fixed == current:
            iterations[-1]["note"] = "no fix applied"
            break
        current = fixed

    changed = current != original
    if changed:
        target.write_text(current, encoding="utf-8")
        store.audit(uid, "self_correct", path, f"iterations={len(iterations)}")

    rows = [
        [it["iteration"], it["verdict"], str(it["risk_score"]), str(it["findings"])]
        for it in iterations
    ]
    table = rich_table(
        ["Iter", "Verdict", "Risk", "Findings"],
        rows,
        title=f"🔄 Self-Correction: {esc(path)}",
        max_width=16,
    )

    diff = ""
    if changed:
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                current.splitlines(),
                lineterm="",
                n=2,
            )
        )
        if diff_lines:
            diff = "<pre>" + esc("\n".join(diff_lines[:40])) + "</pre>"

    text = (
        f"{table}\n"
        f"{G['bullet']} Changes applied: <b>{'yes' if changed else 'no'}</b>\n"
        f"{diff}"
    )
    send_text(message.chat.id, text)


def register_agent(bot_instance: telebot.TeleBot) -> None:
    """Register coding-agent command handlers."""
    b = bot_instance

    @b.message_handler(commands=["selfcorrect"])
    @catch_errors
    def _selfcorrect(m: types.Message) -> None:
        agent_self_correct(m)
