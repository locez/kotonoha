"""Parse standard LRC (line-timed) lyrics and merge a translation track.

Used as the fallback when a song has no word-timed (YRC) lyrics, and to attach
Netease ``tlyric`` (also LRC) onto the main lines by timestamp.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..model import LyricLine

# [mm:ss], [mm:ss.xx] or [mm:ss.xxx]; a line may carry several time tags.
_TIME = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[LyricLine]:
    entries: list[tuple[float, str]] = []
    for raw in text.splitlines():
        tags = list(_TIME.finditer(raw))
        if not tags:
            continue
        content = raw[tags[-1].end() :].strip()
        if not content:
            continue
        for tag in tags:
            minutes = int(tag.group(1))
            seconds = int(tag.group(2))
            frac = tag.group(3) or ""
            millis = int((frac + "000")[:3]) if frac else 0
            entries.append((minutes * 60 + seconds + millis / 1000.0, content))

    entries.sort(key=lambda e: e[0])
    out: list[LyricLine] = []
    for i, (start, content) in enumerate(entries):
        end = entries[i + 1][0] if i + 1 < len(entries) else start + 5.0
        out.append(
            LyricLine(index=i, id=f"L{i}", start=start, end=end, text=content, translation="", words=())
        )
    return out


def merge_translation(base: list[LyricLine], translation: list[LyricLine], tolerance: float = 0.4) -> list[LyricLine]:
    """Attach each translation line to the base line with the nearest start time."""
    if not translation:
        return base
    out: list[LyricLine] = []
    for line in base:
        best_text: str | None = None
        best_delta = tolerance
        for tl in translation:
            delta = abs(tl.start - line.start)
            if delta <= best_delta:
                best_delta = delta
                best_text = tl.text
        out.append(replace(line, translation=best_text) if best_text else line)
    return out
