"""Load timed lyrics from a local audio file or its metadata."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..file_access import BoundedRegularFileReader
from .lrc_parser import parse_lrc
from .models import LyricLine
from .ttml_parser import parse_ttml

#: A sidecar is a lyric file; anything near this size is not one. The read is
#: bounded because the path comes from a player, not from this program.
MAX_SIDECAR_BYTES = 4 * 1024 * 1024


class SidecarLyricsReader:
    """Own adjacent-file validation and format selection through a bounded reader."""

    def __init__(self, reader: BoundedRegularFileReader) -> None:
        self._reader: BoundedRegularFileReader = reader

    def read(self, audio_path: Path) -> list[LyricLine]:
        """Prefer actual word timing, using TTML before LRC when quality ties."""
        if not audio_path.name:
            # file:/// has no adjacent file name; with_suffix would raise.
            return []
        best: list[LyricLine] = []
        try:
            audio_directory = audio_path.parent.resolve()
        except OSError:
            return []
        for suffix in (".ttml", ".lrc"):
            sidecar = audio_path.with_suffix(suffix)
            try:
                raw = None if sidecar.resolve().parent != audio_directory else self._reader.read(sidecar).data
            except OSError:
                continue
            if raw is None:
                continue
            lines: list[LyricLine] = []
            if suffix == ".ttml":
                lines = parse_ttml(raw)
            else:
                for encoding in ("utf-8-sig", "gb18030"):
                    try:
                        lines = parse_lrc(raw.decode(encoding))
                    except UnicodeDecodeError:
                        continue
                    if lines:
                        break
            if any(line.has_word_timing for line in lines):
                return lines
            if not best:
                best = lines
        return best


def load_local_lyrics(audio_path: Path) -> list[LyricLine]:
    """Return the best timed lyrics from adjacent files and embedded tags.

    Two sources, tried in order: TTML/LRC files sitting beside the audio, then the
    lyrics embedded in the audio's own tags. The name says which job this is,
    because a function called load_sidecar that also parses tags left every caller
    having to know that its name described half of what it did.
    Word timing wins; sidecar lyrics win a tie. These public boundary helpers own
    no long-lived state: each read closes its descriptors before returning.
    """
    sidecar = load_sidecar_lyrics(audio_path)
    if any(line.has_word_timing for line in sidecar):
        return sidecar
    embedded = load_embedded_lyrics(audio_path)
    if any(line.has_word_timing for line in embedded):
        return embedded
    return sidecar if sidecar else embedded


def load_sidecar_lyrics(audio_path: Path) -> list[LyricLine]:
    """Read adjacent TTML/LRC files through the bounded local-file boundary."""
    return SidecarLyricsReader(BoundedRegularFileReader(MAX_SIDECAR_BYTES)).read(audio_path)


def load_embedded_lyrics(audio_path: Path) -> list[LyricLine]:
    """Return timed lines from the audio file's own tags.

    The path came from a player, so the file is opened once and judged through
    that descriptor rather than by name: checking the name and then letting the
    tag reader reopen it leaves a window in which a regular file becomes a pipe.
    The same handle is what the reader is given, so there is nothing to re-resolve.
    """
    try:
        # Optional: the feature exists only where the user installed it, so the
        # type checker must not treat an absent import as an error.
        import mutagen  # ty: ignore[unresolved-import]
    except ImportError:
        return []

    try:
        descriptor = os.open(audio_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return []
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return []
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            audio = mutagen.File(handle)
            if audio is None or audio.tags is None:
                return []
            best: list[LyricLine] = []
            for text in _embedded_texts(audio.tags):
                normalized = text.lstrip("\ufeff \t\r\n")
                lines = parse_ttml(normalized) if normalized.startswith("<") else parse_lrc(normalized)
                if any(line.has_word_timing for line in lines):
                    return lines
                if not best:
                    best = lines
            return best
    except (AttributeError, KeyError, IndexError, OSError, TypeError, ValueError, mutagen.MutagenError):
        return []
    finally:
        os.close(descriptor)
    return []


def _embedded_texts(tags: object) -> list[str]:
    """Return candidate text values from the supported mutagen tag shapes."""
    candidates: list[str] = []

    getall = getattr(tags, "getall", None)
    if callable(getall):
        for frame in getall("USLT"):
            text = getattr(frame, "text", None)
            if isinstance(text, str):
                candidates.append(text)

    get = getattr(tags, "get", None)
    if not callable(get):
        return candidates

    # Vorbis comments (FLAC, Ogg) accept only printable ASCII keys and raise
    # ValueError on anything else, so probing the MP4 key on a FLAC threw before
    # the LYRICS value already found here could be returned — every FLAC with
    # embedded lyrics came back empty. Each lookup is therefore isolated.
    for key in ("LYRICS", "UNSYNCEDLYRICS", "\u00a9lyr", b"\xa9lyr"):
        try:
            values = get(key, [])
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(values, str):
            values = [values]
        if isinstance(values, (list, tuple)):
            candidates.extend(value for value in values if isinstance(value, str))

    return candidates
