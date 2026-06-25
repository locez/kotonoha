"""Parse Netease YRC (word-timed) lyrics into LyricLine objects.

YRC line format (confirmed against the live api/song/lyric/v1 response):

    [lineStartMs,lineDurMs](wordStartMs,wordDurMs,0)字(wordStartMs,wordDurMs,0)字…

A few leading lines are JSON metadata ({"t":..,"c":[..]}, e.g. 作词/作曲) and are
skipped. Word text is whatever follows a ``)`` up to the next ``(`` (may contain
spaces); the line text is the exact concatenation of word texts so the karaoke
sweep geometry lines up.
"""

from __future__ import annotations

import re

from ..model import LyricLine, LyricWord

_LINE_HEAD = re.compile(r"^\[(\d+),(\d+)\]")
_WORD = re.compile(r"\((\d+),(\d+),\d+\)([^(]*)")


def parse_yrc(text: str) -> list[LyricLine]:
    lines: list[LyricLine] = []
    index = 0
    for raw in text.splitlines():
        head = _LINE_HEAD.match(raw)
        if head is None:  # JSON metadata / blank / non-timed
            continue
        line_start = int(head.group(1)) / 1000.0
        line_end = (int(head.group(1)) + int(head.group(2))) / 1000.0

        words: list[LyricWord] = []
        parts: list[str] = []
        for m in _WORD.finditer(raw):
            w_start = int(m.group(1)) / 1000.0
            w_end = (int(m.group(1)) + int(m.group(2))) / 1000.0
            tx = m.group(3)
            words.append(LyricWord(start=w_start, end=w_end, text=tx))
            parts.append(tx)

        text_line = "".join(parts)
        if not text_line.strip() or not words:
            continue
        lines.append(
            LyricLine(
                index=index,
                id=f"L{index}",
                start=line_start,
                end=line_end,
                text=text_line,
                translation="",
                words=tuple(words),
            )
        )
        index += 1
    return lines
