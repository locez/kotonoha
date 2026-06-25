"""Pick the best lyrics candidate for a now-playing track.

Search results are noisy (live/remix/covers/same name), so matching leans
heavily on the MPRIS track **duration** as ground truth, with title/artist as a
coarse filter. Title/artist are normalized (drop bracketed notes, feat., case,
punctuation) before comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARENS = re.compile(r"[\(（\[【].*?[\)）\]】]")
_FEAT = re.compile(r"\b(feat|ft)\.?.*", re.IGNORECASE)
_KEEP = re.compile(r"[^\w一-鿿]+")


@dataclass(frozen=True)
class Candidate:
    song_id: str
    title: str
    artist: str
    duration_s: float | None


def normalize(text: str) -> str:
    text = text.lower()
    text = _PARENS.sub("", text)
    text = _FEAT.sub("", text)
    return _KEEP.sub("", text).strip()


def score(candidate: Candidate, title: str, artist: str, duration_s: float | None) -> float:
    total = 0.0
    nt, na = normalize(title), normalize(artist)
    ct, ca = normalize(candidate.title), normalize(candidate.artist)

    if nt and (nt in ct or ct in nt):
        total += 2.0
    if na and ca and (na in ca or ca in na):
        total += 1.0

    if duration_s and candidate.duration_s:
        diff = abs(duration_s - candidate.duration_s)
        if diff <= 3.0:
            total += 3.0
        elif diff <= 8.0:
            total += 1.0
        else:
            total -= diff / 30.0  # far-off duration is a strong negative
    return total


def best_match(
    candidates: list[Candidate],
    title: str,
    artist: str,
    duration_s: float | None,
    min_score: float = 2.0,
) -> Candidate | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda c: score(c, title, artist, duration_s))
    return best if score(best, title, artist, duration_s) >= min_score else None
