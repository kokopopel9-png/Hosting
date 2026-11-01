"""Text formatting helpers: escaping, byte/duration formatting, rich tables.

Telegram's HTML parse mode is used for rich output. ``rich_table`` renders a
borderless Markdown/HTML-style table that displays cleanly in most clients;
for maximum compatibility it falls back to a monospaced aligned table wrapped
in ``<pre>``.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Sequence


def esc(text: str) -> str:
    """Escape a string for Telegram HTML parse mode."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def esc_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"_*[]()~`>#+-=|{}.!\\":
        text = text.replace(ch, "\\" + ch)
    return text


def fmt_bytes(num: float) -> str:
    """Human-readable byte count."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:,.2f} {unit}"
        num /= 1024.0
    return f"{num:,.2f} PB"


def fmt_dur(ms: int) -> str:
    """Human-readable duration from milliseconds."""
    s = ms / 1000.0
    if s < 60:
        return f"{s:.2f}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{int(m)}m {s:.0f}s"
    h, m = divmod(int(m), 60)
    return f"{h}h {m}m {int(s)}s"


def progress_bar(pct: int, width: int = 20) -> str:
    """ASCII progress bar, ``pct`` in 0..100."""
    pct = max(0, min(100, pct))
    filled = int(width * pct / 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct}%"


def rich_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    title: str = "",
    max_width: int = 30,
    use_pre: bool = True,
) -> str:
    """Render a rich table for Telegram.

    Parameters
    ----------
    headers:
        Column titles.
    rows:
        Row data (each cell converted to str).
    title:
        Optional bold title shown above the table.
    max_width:
        Max characters per cell before truncation.
    use_pre:
        When True (default), wraps the aligned table in ``<pre>`` so columns
        stay aligned in Telegram HTML mode. When False returns an HTML
        ``<table>`` (rendering depends on the client).

    Returns
    -------
    str
        HTML-safe string ready for ``parse_mode="HTML"``.
    """

    def _cell(value: Any) -> str:
        text = esc(str(value))
        return (text[: max_width - 1] + "…") if len(text) > max_width else text

    cols = [_cell(h) for h in headers]
    widths = [len(c) for c in cols]
    data_rows: List[List[str]] = []
    for row in rows:
        cells = [_cell(v) for v in row]
        data_rows.append(cells)
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))

    def _fmt_row(cells: Sequence[str]) -> str:
        return " │ ".join(c.ljust(widths[i]) for i, c in enumerate(cells))

    lines: List[str] = []
    if title:
        lines.append(f"<b>{esc(title)}</b>")
    if use_pre:
        lines.append("<pre>")
        lines.append(_fmt_row(cols))
        lines.append("─┼─".join("─" * w for w in widths))
        for cells in data_rows:
            lines.append(_fmt_row(cells))
        lines.append("</pre>")
    else:
        lines.append("<table>")
        lines.append("<tr>" + "".join(f"<td><b>{c}</b></td>" for c in cols) + "</tr>")
        for cells in data_rows:
            lines.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        lines.append("</table>")
    return "\n".join(lines)


def chunk_text(text: str, size: int = 3500) -> List[str]:
    """Split ``text`` into chunks under Telegram's message limit."""
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks
