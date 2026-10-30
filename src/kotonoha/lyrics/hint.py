"""Extract provider-owned lyric identifiers from MPRIS metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class LyricsHint:
    """An exact lyric source a player already knows, so no matching is needed.

    ``provider`` names the identifier's platform; enabled sources may share its
    identity, such as AMLL's NetEase song IDs. ``song_id`` carries the network
    identifier for netease or qqmusic; ``local_path`` carries the
    audio file for the "local" provider. Only the field the provider uses is
    populated, and the other is None.
    """

    provider: str
    song_id: str | None = None
    local_path: Path | None = None


def from_player(identity: str, bus_name: str, track_id: str, url: str) -> LyricsHint | None:
    """Return an exact provider id, or a local path, for known players only."""
    if identity in {"ElectronNCM", "Qcm"} or "musicfox" in bus_name or "NeteaseCloudMusicGtk4" in bus_name:
        song_id = track_id.rsplit("/", 1)[-1]
        return LyricsHint("netease", song_id) if song_id else None
    if identity == "feeluown":
        for prefix, provider in (("fuo://netease/songs/", "netease"), ("fuo://qqmusic/songs/", "qqmusic")):
            if url.startswith(prefix):
                song_id = url.removeprefix(prefix)
                return LyricsHint(provider, song_id) if song_id else None
    if identity == "YesPlayMusic" and url.startswith("/trackid/"):
        song_id = url.removeprefix("/trackid/")
        return LyricsHint("netease", song_id) if song_id else None
    if url.startswith("file://"):
        parsed = urlparse(url)
        # RFC 8089: a file URI names a local file only when its authority is empty
        # or "localhost". "file://remote.example/etc/song.flac" was read as the local
        # path /etc/song.flac, so a player's metadata chose which local file to open.
        if parsed.netloc not in ("", "localhost"):
            return None
        if parsed.path:
            return LyricsHint("local", local_path=Path(unquote(parsed.path)))
    return None
