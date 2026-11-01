"""Security watchdog: dangerous-command blocking and code scanning.

Defines a set of command patterns that are never allowed to run on the
server (data exfiltration, destructive system ops, credential dumping, etc.)
and a lightweight static scanner for user-submitted code.
"""

from __future__ import annotations

import ast
import os
import re
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────────────────────────────────────────────────────────
#  Blocked terminal command patterns (never executed by /exec or agent)
# ──────────────────────────────────────────────────────────────────────
BLOCKED_COMMAND_PATTERNS: List[Tuple[str, str]] = [
    (r"\brm\b.*-rf\s+/", "Recursive root deletion (rm -rf /)"),
    (r"\bdd\b", "Low-level disk write (dd)"),
    (r"\bmkfs\b", "Filesystem formatting (mkfs)"),
    (r">\s*/dev/(sda|hda|vda|nvme)", "Raw block device write"),
    (r":\(\)\{\s*:\|:&\s*\};:", "Fork bomb"),
    (r"\bcurl\b.*\|\s*\b(sh|bash|python)\b", "Pipe to shell (curl | sh)"),
    (r"\bwget\b.*\|\s*\b(sh|bash|python)\b", "Pipe to shell (wget | sh)"),
    (r"\bsudo\b.*\b(passwd|usermod|userdel)\b", "Credential / account change via sudo"),
    (r"\bchmod\s+777\s+/", "World-writable root permission"),
    (r"\bchown\s+.*\s+/", "Recursive chown on root"),
    (r"\bmount\b", "Mount syscalls"),
    (r"\bumount\b", "Unmount syscalls"),
    (r"\biptables\b", "Firewall manipulation"),
    (r"\bsystemctl\s+(stop|disable)\b", "Critical service stop/disable"),
]


def is_blocked_command(command: str) -> Tuple[bool, Optional[str]]:
    """Return ``(blocked, reason)`` for a shell command string."""
    for pattern, reason in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, reason
    return False, None


# ──────────────────────────────────────────────────────────────────────
#  Static code scan (lightweight AST + regex)
# ──────────────────────────────────────────────────────────────────────
_DANGEROUS_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.check_output",
    "eval",
    "exec",
    "compile",
    "__import__",
}


def scan_code(code: str, filename: str = "file.py") -> Dict[str, Any]:
    """Statically scan ``code`` for risky constructs.

    Returns a dict with ``risk_score`` (0-100), ``verdict`` and ``findings``.
    """
    findings: List[Dict[str, str]] = []

    # Regex-based findings.
    for pattern, reason in BLOCKED_COMMAND_PATTERNS:
        if re.search(pattern, code):
            findings.append({"rule": pattern, "reason": reason, "severity": "high"})

    # AST-based findings.
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        findings.append({"rule": "syntax", "reason": str(exc), "severity": "high"})
        tree = None

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name: Optional[str] = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = f"{_attr_name(func.value)}.{func.attr}"
                if name and name in _DANGEROUS_CALLS:
                    findings.append(
                        {
                            "rule": f"call:{name}",
                            "reason": f"Potentially dangerous call: {name}",
                            "severity": "medium",
                        }
                    )

    risk_score = min(100, len(findings) * 20)
    if risk_score >= 60:
        verdict = "BLOCKED"
    elif risk_score >= 30:
        verdict = "WARNING"
    else:
        verdict = "SAFE"

    return {
        "filename": filename,
        "risk_score": risk_score,
        "verdict": verdict,
        "findings": findings,
        "safe": verdict == "SAFE",
    }


def _attr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_attr_name(node.value)}.{node.attr}"
    return ""


def is_dangerous_code(code: str) -> bool:
    """Convenience: True when static scan returns BLOCKED."""
    return not scan_code(code)["safe"]
