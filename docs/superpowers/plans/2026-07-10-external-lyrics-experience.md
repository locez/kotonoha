# External Lyrics Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MPRIS track changes stable, improve external lyric matching and fetch reliability, and add provider-scoped persistent caching while preserving configured provider order and the existing HUD renderer.

**Architecture:** Introduce small pure domain objects for track matching and MPRIS stabilization, make network providers return cacheable lyric artifacts, and route configured providers through one ordered resolver. Evolve the existing Cider gate into a connection-aware live-source store, but keep the TypeScript protocol and all overlay/karaoke/layer-shell files unchanged.

**Tech Stack:** Python 3.10+, asyncio, aiohttp, dbus-fast, sqlite3, PyQt6/qasync, pytest, Ruff, ty.

---

## File Map

Create:

- `src/kotonoha/lyrics/artifact.py` - provider-neutral fetched lyric artifact and cached payload model.
- `src/kotonoha/lyrics/cache.py` - XDG SQLite persistence, matching lookup, pruning, and clear operations.
- `src/kotonoha/lyrics/resolver.py` - exact configured-provider walk and in-flight request deduplication.
- `src/kotonoha/providers/mpris_track.py` - pure MPRIS metadata parsing, observations, and stabilization.
- `tests/test_lyrics_providers.py` - provider response, query variant, and fallback tests.
- `tests/test_lyrics_cache.py` - persistent cache behavior tests.
- `tests/test_lyrics_resolver.py` - provider/cache/Cider ordering tests.
- `tests/test_mpris_provider.py` - async MPRIS transition and cancellation tests.
- `tests/test_settings_dialog.py` - offscreen cache-control behavior.

Modify:

- `src/kotonoha/lyrics/match.py` - Unicode normalization, qualifiers, structured confidence, and query variants.
- `src/kotonoha/lyrics/netease.py` - validated provider artifacts and YRC-to-LRC fallback.
- `src/kotonoha/lyrics/lrclib.py` - exact/search artifacts and ranked search results.
- `src/kotonoha/providers/gate.py` - retained Cider snapshots, connection binding, and tick gating.
- `src/kotonoha/receiver.py` - identify WS clients, retain frames while closed, and gate ticks.
- `src/kotonoha/providers/mpris.py` - stable sampling, cancellable generations, resolver integration, and actual provider labels.
- `src/kotonoha/config.py` - `cache_enabled` setting.
- `src/kotonoha/settings_dialog.py` - cache checkbox and clear command in the Sources tab.
- `src/kotonoha/controller.py` - apply cache setting and schedule cache clearing.
- `src/kotonoha/strings.py` - localized cache controls.
- `tests/test_lyrics.py` - normalization and confidence cases.
- `tests/test_mpris.py` - metadata parsing and stabilizer compatibility exports.
- `tests/test_gate.py` - Cider ordering and connection ownership.
- `tests/test_receiver.py` - closed-gate snapshot retention and tick rejection.
- `tests/test_config.py` - cache setting persistence.
- `tests/test_strings.py` - existing complete-language check covers new strings.
- `README.md` - provider-local cache sequence and troubleshooting notes.
- `docs/SPEC-mpris-lyrics.md` - align the older MPRIS design with implemented ordering/cache semantics.

Do not modify `overlay.py`, `karaoke_label.py`, `karaoke.py`, `native.py`, `layer_shell_bridge.cpp`, or files under `plugins/cider/lyrics/src/`.

### Task 1: Define Track Matching And Confidence

**Files:**
- Modify: `src/kotonoha/lyrics/match.py`
- Modify: `tests/test_lyrics.py`

- [ ] **Step 1: Write failing normalization and confidence tests**

Add tests that state the contract directly:

```python
from kotonoha.lyrics.match import (
    Candidate,
    MatchConfidence,
    TrackMetadata,
    best_match,
    evaluate_match,
    normalize,
    query_variants,
)


def test_normalize_uses_nfkc_and_safe_feat_boundaries():
    assert normalize("Ｓｏｎｇ") == "song"
    assert normalize("Feather") == "feather"
    assert normalize("FTISLAND") == "ftisland"
    assert normalize("Song feat. Guest") == "song"


def test_duration_alone_is_not_a_match():
    track = TrackMetadata("Target", "Artist", "", 180.0)
    candidate = Candidate("1", "Other", "Someone", 180.0)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_explicit_live_version_conflict_is_rejected():
    track = TrackMetadata("Song", "Artist", "Album", 200.0)
    candidate = Candidate("1", "Song (Live)", "Artist", 200.5, album="Album")
    assert evaluate_match(candidate, track).confidence is MatchConfidence.NONE


def test_artist_order_does_not_change_identity():
    track = TrackMetadata("Song", "A / B", "", 180.0)
    candidate = Candidate("1", "Song", "B, A", 180.5)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.HIGH


def test_missing_artist_and_duration_is_not_persistent_confidence():
    track = TrackMetadata("Song", "")
    candidate = Candidate("1", "Song", "Other Artist", None)
    assert evaluate_match(candidate, track).confidence is MatchConfidence.MEDIUM


def test_query_variants_are_raw_then_base_title_primary_artist():
    track = TrackMetadata("Song (Remastered 2011)", "A feat. B", "Album", 180.0)
    assert query_variants(track) == (
        "Song (Remastered 2011) A feat. B",
        "Song A",
    )
```

- [ ] **Step 2: Run the matching tests and confirm failure**

Run:

```bash
uv run pytest tests/test_lyrics.py -q
```

Expected: FAIL because `MatchConfidence`, `TrackMetadata`, `evaluate_match`, and `query_variants` do not exist, and the old normalizer damages `Feather`/`FTISLAND`.

- [ ] **Step 3: Replace scalar-only matching with structured evidence**

Implement these public types and functions in `match.py` while retaining `normalize()` as a public compatibility helper:

```python
from enum import Enum
from unicodedata import normalize as unicode_normalize


class MatchConfidence(str, Enum):
    NONE = "none"
    MEDIUM = "medium"
    HIGH = "high"


NORMALIZER_VERSION = 1


@dataclass(frozen=True)
class TrackMetadata:
    title: str
    artist: str
    album: str = ""
    duration_s: float | None = None


@dataclass(frozen=True)
class Candidate:
    song_id: str
    title: str
    artist: str
    duration_s: float | None
    album: str = ""


@dataclass(frozen=True)
class MatchEvidence:
    candidate: Candidate
    confidence: MatchConfidence
    title_exact: bool
    artist_overlap: bool
    album_match: bool
    duration_delta: float | None
    version_conflict: bool


def normalize(text: str) -> str:
    value = unicode_normalize("NFKC", text).casefold()
    value = _FEAT_SUFFIX.sub("", value)
    return _KEEP.sub("", value).strip()


def evaluate_match(candidate: Candidate, track: TrackMetadata) -> MatchEvidence:
    track_base, track_tags = split_title(track.title)
    candidate_base, candidate_tags = split_title(candidate.title)
    normalized_track = normalize(track_base)
    normalized_candidate = normalize(candidate_base)
    title_exact = bool(normalized_track) and normalized_track == normalized_candidate
    title_ratio = SequenceMatcher(None, normalized_track, normalized_candidate).ratio()
    title_strong = title_exact or (
        min(len(normalized_track), len(normalized_candidate)) >= 4 and title_ratio >= 0.88
    )
    track_artists = artist_tokens(track.artist)
    candidate_artists = artist_tokens(candidate.artist)
    artist_overlap = not track_artists or not candidate_artists or bool(track_artists & candidate_artists)
    artist_evidence = bool(track_artists and candidate_artists and track_artists & candidate_artists)
    album_match = bool(track.album and candidate.album and normalize(track.album) == normalize(candidate.album))
    duration_delta = (
        abs(track.duration_s - candidate.duration_s)
        if track.duration_s is not None and candidate.duration_s is not None
        else None
    )
    version_conflict = bool(track_tags or candidate_tags) and track_tags != candidate_tags

    confidence = MatchConfidence.NONE
    if not version_conflict and artist_overlap:
        supporting_identity = artist_evidence or album_match or (
            duration_delta is not None and duration_delta <= 3.0
        )
        if title_strong and supporting_identity and (duration_delta is None or duration_delta <= 3.0):
            confidence = MatchConfidence.HIGH
        elif title_strong and (duration_delta is None or duration_delta <= 8.0):
            confidence = MatchConfidence.MEDIUM
        elif not title_strong and track_artists and candidate_artists and duration_delta is not None:
            if duration_delta <= 3.0 and (album_match or track_artists == candidate_artists):
                confidence = MatchConfidence.MEDIUM

    return MatchEvidence(
        candidate=candidate,
        confidence=confidence,
        title_exact=title_exact,
        artist_overlap=artist_overlap,
        album_match=album_match,
        duration_delta=duration_delta,
        version_conflict=version_conflict,
    )


def best_match(candidates: list[Candidate], track: TrackMetadata) -> MatchEvidence | None:
    matches = [evaluate_match(candidate, track) for candidate in candidates]
    usable = [match for match in matches if match.confidence is not MatchConfidence.NONE]
    return max(usable, key=_evidence_sort_key, default=None)


def query_variants(track: TrackMetadata) -> tuple[str, ...]:
    raw = f"{track.title} {track.artist}".strip()
    fallback = f"{base_title(track.title)} {primary_artist(track.artist)}".strip()
    return tuple(dict.fromkeys(value for value in (raw, fallback) if value))
```

Implement `split_title()`, `artist_tokens()`, `primary_artist()`, and `_evidence_sort_key()` in the same file. Use `difflib.SequenceMatcher` and a suffix pattern with boundaries on both sides of the marker, for example `r"\b(?:feat(?:uring)?|ft)\b\.?.*$"`; this must not match the `ft` prefix in `FTISLAND`. Keep qualifier extraction separate from base-title normalization. `_evidence_sort_key()` must order `HIGH` before `MEDIUM`, then prefer exact title, artist overlap, album match, and smaller duration delta.

- [ ] **Step 4: Update old tests to use the new `best_match` signature**

Change existing calls from separate title/artist/duration arguments to `TrackMetadata`, and assert `match.candidate.song_id` plus `match.confidence`.

- [ ] **Step 5: Run matching tests**

Run:

```bash
uv run pytest tests/test_lyrics.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit matching behavior**

```bash
git add src/kotonoha/lyrics/match.py tests/test_lyrics.py
git commit -m "feat(lyrics): harden track matching confidence"
```

### Task 2: Make Providers Return Cacheable Artifacts

**Files:**
- Create: `src/kotonoha/lyrics/artifact.py`
- Modify: `src/kotonoha/lyrics/netease.py`
- Modify: `src/kotonoha/lyrics/lrclib.py`
- Create: `tests/test_lyrics_providers.py`

- [ ] **Step 1: Write failing provider artifact tests**

Use monkeypatches around provider search/fetch helpers so tests do not access the network:

```python
def async_return(value):
    async def result(*_args, **_kwargs):
        return value

    return result


async def test_netease_empty_parsed_yrc_falls_back_to_lrc(monkeypatch):
    async def fake_search(_session, _query, limit=10):
        return [Candidate("42", "Song", "Artist", 180.0, album="Album")]

    async def fake_payload(_session, _song_id):
        return {"yrc": "not valid yrc", "lrc": "[00:01.00]line", "tlyric": ""}

    monkeypatch.setattr(netease, "search", fake_search)
    monkeypatch.setattr(netease, "fetch_payload", fake_payload)

    artifact = await netease.fetch_artifact(None, TrackMetadata("Song", "Artist", "Album", 180.0))
    assert artifact is not None
    assert artifact.provider_song_id == "42"
    assert [line.text for line in artifact.lines] == ["line"]


async def test_lrclib_search_ranks_results_instead_of_taking_first(monkeypatch):
    monkeypatch.setattr(lrclib, "get_exact", async_return(None))
    monkeypatch.setattr(
        lrclib,
        "search_records",
        async_return(
            [
                lrclib.Record("wrong", "Song (Live)", "Artist", "", 240.0, "[00:01]wrong"),
                lrclib.Record("right", "Song", "Artist", "Album", 180.0, "[00:01]right"),
            ]
        ),
    )

    artifact = await lrclib.fetch_artifact(None, TrackMetadata("Song", "Artist", "Album", 180.0))
    assert artifact is not None
    assert artifact.provider_song_id == "right"
```

- [ ] **Step 2: Run provider tests and confirm failure**

Run:

```bash
uv run pytest tests/test_lyrics_providers.py -q
```

Expected: FAIL because the artifact APIs do not exist.

- [ ] **Step 3: Add the provider-neutral artifact model**

Create `artifact.py`:

```python
@dataclass(frozen=True)
class LyricsArtifact:
    provider: str
    provider_song_id: str
    title: str
    artist: str
    album: str
    duration_s: float | None
    payload: dict[str, str]
    lines: tuple[LyricLine, ...]
    confidence: MatchConfidence

    @property
    def candidate(self) -> Candidate:
        return Candidate(
            song_id=self.provider_song_id,
            title=self.title,
            artist=self.artist,
            duration_s=self.duration_s,
            album=self.album,
        )
```

- [ ] **Step 4: Implement Netease artifact fetching**

Split Netease into explicit helpers:

```python
async def fetch_payload(session: aiohttp.ClientSession, song_id: str) -> dict[str, str]:
    params = {"id": song_id, "lv": "1", "kv": "0", "tv": "1", "yv": "1"}
    async with session.get(LYRIC_URL, params=params, headers=HEADERS) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)
    if not isinstance(data, dict):
        raise ValueError("Netease lyric response is not an object")
    return {
        "yrc": lyric_text(data, "yrc"),
        "lrc": lyric_text(data, "lrc"),
        "tlyric": lyric_text(data, "tlyric"),
    }


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    yrc_lines = parse_yrc(payload.get("yrc", ""))
    base = yrc_lines or parse_lrc(payload.get("lrc", ""))
    translation = parse_lrc(payload.get("tlyric", ""))
    return tuple(merge_translation(base, translation) if translation else base)


async def fetch_artifact(
    session: aiohttp.ClientSession,
    track: TrackMetadata,
) -> LyricsArtifact | None:
    for query in query_variants(track):
        candidates = await search(session, query)
        match = best_match(candidates, track)
        if match is None:
            continue
        payload = await fetch_payload(session, match.candidate.song_id)
        lines = parse_payload(payload)
        if lines:
            candidate = match.candidate
            return LyricsArtifact(
                provider="netease",
                provider_song_id=candidate.song_id,
                title=candidate.title,
                artist=candidate.artist,
                album=candidate.album,
                duration_s=candidate.duration_s,
                payload=payload,
                lines=lines,
                confidence=match.confidence,
            )
    return None
```

Check HTTP status and dictionary/list shapes before reading fields. Do not turn a missing ID into the string `"None"`.
Add `lyric_text(data, key)` as a narrow helper that returns `data[key]["lyric"]` only when both levels are dictionaries and the final value is a string; otherwise return `""`.

- [ ] **Step 5: Implement LRCLIB records and artifact fetching**

Add a frozen `Record` dataclass, `get_exact()`, `search_records()`, `parse_payload()`, and `fetch_artifact()`. Convert every search record with synchronized lyrics into a `Candidate`, call `best_match()`, and return the chosen `LyricsArtifact`. Keep `/api/get` and `/api/search` exception boundaries separate so a failed exact request still reaches search.

```python
@dataclass(frozen=True)
class Record:
    song_id: str
    title: str
    artist: str
    album: str
    duration_s: float | None
    synced_lyrics: str


def parse_payload(payload: Mapping[str, str]) -> tuple[LyricLine, ...]:
    return tuple(parse_lrc(payload.get("syncedLyrics", "")))


async def fetch_artifact(session, track):
    exact = None
    try:
        exact = await get_exact(session, track)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        logger.debug("LRCLIB exact lookup failed, trying search: %s", exc)
    records = [exact] if exact is not None else await search_records(session, track)
    candidates = [
        Candidate(record.song_id, record.title, record.artist, record.duration_s, album=record.album)
        for record in records
        if record.synced_lyrics
    ]
    match = best_match(candidates, track)
    if match is None:
        return None
    record = next(item for item in records if item.song_id == match.candidate.song_id)
    payload = {"syncedLyrics": record.synced_lyrics}
    lines = parse_payload(payload)
    if not lines:
        return None
    return LyricsArtifact(
        provider="lrclib",
        provider_song_id=record.song_id,
        title=record.title,
        artist=record.artist,
        album=record.album,
        duration_s=record.duration_s,
        payload=payload,
        lines=lines,
        confidence=match.confidence,
    )
```

Let final network/JSON failures propagate to `LyricsResolver` after logging provider context there. A normal `None` return must mean the provider completed successfully but found no confident usable lyrics; this distinction is required for the memory-only negative cache in Task 5.

- [ ] **Step 6: Keep temporary compatibility wrappers**

Retain `fetch(session, title, artist, duration_s)` in both modules as a wrapper around `fetch_artifact()` returning `list(artifact.lines)` until `MprisProvider` switches to `LyricsResolver` in Task 6.

- [ ] **Step 7: Run provider and parser tests**

Run:

```bash
uv run pytest tests/test_lyrics.py tests/test_lyrics_providers.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit provider artifacts**

```bash
git add src/kotonoha/lyrics/artifact.py src/kotonoha/lyrics/netease.py src/kotonoha/lyrics/lrclib.py tests/test_lyrics_providers.py
git commit -m "feat(lyrics): return cacheable provider artifacts"
```

### Task 3: Add Provider-Scoped SQLite Cache

**Files:**
- Create: `src/kotonoha/lyrics/cache.py`
- Create: `tests/test_lyrics_cache.py`

- [ ] **Step 1: Write failing cache tests**

Cover provider isolation, dynamic metadata matching, clearing, and LRU pruning:

```python
def artifact(
    *,
    provider: str = "netease",
    provider_song_id: str = "1",
) -> LyricsArtifact:
    return LyricsArtifact(
        provider=provider,
        provider_song_id=provider_song_id,
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload={"lrc": "[00:01.00]line", "yrc": "", "tlyric": ""},
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=MatchConfidence.HIGH,
    )


async def test_lookup_is_scoped_to_provider_and_matches_metadata(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", max_entries=10)
    await cache.store(artifact(provider="netease", provider_song_id="1"))
    await cache.store(artifact(provider="lrclib", provider_song_id="2"))

    track = TrackMetadata("Ｓｏｎｇ", "Artist", "Album", 180.0)
    hit = await cache.lookup("netease", track, netease.parse_payload)

    assert hit is not None
    assert hit.provider == "netease"
    assert hit.provider_song_id == "1"


async def test_lookup_does_not_use_player_or_search_key(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(provider="netease", provider_song_id="1"))
    assert await cache.lookup("netease", TrackMetadata("Song", "Artist", "", 180.0), netease.parse_payload)


async def test_clear_and_lru_pruning(tmp_path):
    cache = LyricsCache(tmp_path / "lyrics.sqlite3", max_entries=2)
    await cache.store(artifact(provider_song_id="1"))
    await cache.store(artifact(provider_song_id="2"))
    await cache.store(artifact(provider_song_id="3"))
    assert await cache.count() == 2
    await cache.clear()
    assert await cache.count() == 0
```

- [ ] **Step 2: Run cache tests and confirm failure**

Run:

```bash
uv run pytest tests/test_lyrics_cache.py -q
```

Expected: FAIL because `LyricsCache` does not exist.

- [ ] **Step 3: Implement XDG path and SQLite schema**

Create `cache.py` with:

```python
CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 1000


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "kotonoha" / "lyrics.sqlite3"


class LyricsCache:
    def __init__(self, path: Path | None = None, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._path = path or cache_path()
        self._max_entries = max_entries

    async def lookup(
        self,
        provider: str,
        track: TrackMetadata,
        parser: Callable[[Mapping[str, str]], tuple[LyricLine, ...]],
    ) -> LyricsArtifact | None:
        return await asyncio.to_thread(self._lookup_sync, provider, track, parser)

    async def store(self, artifact: LyricsArtifact) -> None:
        if artifact.confidence is MatchConfidence.HIGH:
            await asyncio.to_thread(self._store_sync, artifact)

    async def clear(self) -> None:
        await asyncio.to_thread(self._clear_sync)

    async def count(self) -> int:
        return await asyncio.to_thread(self._count_sync)
```

Use a single `lyrics` table keyed by `(provider, provider_song_id)` with provider metadata, JSON payload, timestamps, and schema/normalizer versions. There must be no MPRIS player, track ID, raw search query, or alias table.

```sql
CREATE TABLE IF NOT EXISTS lyrics (
    provider TEXT NOT NULL,
    provider_song_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    duration_s REAL,
    payload_json TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    normalizer_version INTEGER NOT NULL,
    PRIMARY KEY (provider, provider_song_id)
);
CREATE INDEX IF NOT EXISTS lyrics_provider_access
    ON lyrics(provider, last_accessed DESC);
```

- [ ] **Step 4: Implement matching lookup and invalid-entry recovery**

Load candidate rows only for the requested provider, evaluate them with the shared matcher, select only `HIGH`, parse the stored payload, and update `last_accessed`. If JSON or parsing fails, delete that row and return `None` so the resolver continues to the same provider's network stage.

```python
def _lookup_sync(self, provider, track, parser):
    with self._connect() as connection:
        rows = connection.execute(
            "SELECT * FROM lyrics WHERE provider = ? AND schema_version = ? AND normalizer_version = ?",
            (provider, CACHE_SCHEMA_VERSION, NORMALIZER_VERSION),
        ).fetchall()
        matches = []
        for row in rows:
            candidate = Candidate(
                row["provider_song_id"],
                row["title"],
                row["artist"],
                row["duration_s"],
                album=row["album"],
            )
            evidence = evaluate_match(candidate, track)
            if evidence.confidence is MatchConfidence.HIGH:
                matches.append((evidence, row))
        if not matches:
            return None
        evidence, row = max(
            matches,
            key=lambda item: (
                item[0].title_exact,
                item[0].artist_overlap,
                item[0].album_match,
                -(item[0].duration_delta if item[0].duration_delta is not None else 0.0),
            ),
        )
        try:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise TypeError("cached payload is not an object")
            lines = parser(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            connection.execute(
                "DELETE FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                (provider, row["provider_song_id"]),
            )
            return None
        connection.execute(
            "UPDATE lyrics SET last_accessed = ? WHERE provider = ? AND provider_song_id = ?",
            (time.time(), provider, row["provider_song_id"]),
        )
        return LyricsArtifact(
            provider=provider,
            provider_song_id=row["provider_song_id"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration_s=row["duration_s"],
            payload=payload,
            lines=lines,
            confidence=evidence.confidence,
        )
```

Configure `_connect()` with `sqlite3.Row` and create parent directories before connecting.

- [ ] **Step 5: Implement pruning after successful writes**

After upserting the artifact by `(provider, provider_song_id)`, delete the least-recently-accessed rows above `max_entries` in the same transaction.

```python
connection.execute(
    "DELETE FROM lyrics WHERE rowid IN ("
    "SELECT rowid FROM lyrics ORDER BY last_accessed DESC LIMIT -1 OFFSET ?)",
    (self._max_entries,),
)
```

- [ ] **Step 6: Run cache tests**

Run:

```bash
uv run pytest tests/test_lyrics_cache.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the cache**

```bash
git add src/kotonoha/lyrics/cache.py tests/test_lyrics_cache.py
git commit -m "feat(lyrics): add provider-scoped persistent cache"
```

### Task 4: Make Cider Gate Connection-Aware

**Files:**
- Modify: `src/kotonoha/providers/gate.py`
- Modify: `src/kotonoha/receiver.py`
- Modify: `tests/test_gate.py`
- Modify: `tests/test_receiver.py`

- [ ] **Step 1: Write failing gate ownership tests**

```python
def test_closed_gate_retains_matching_snapshot_without_publishing():
    gate = SourceGate()
    gate.select_external()
    snapshot = LyricsSnapshot(found=True, title="Song", artist="Artist", song_id="am-1")
    gate.observe_snapshot(10, snapshot)

    match = gate.current_match(TrackMetadata("Song", "Artist"))
    assert match is not None
    assert match.client_id == 10
    assert gate.accepts(10) is False


def test_select_cider_binds_one_connection_and_ticks_follow_binding():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    gate.select_cider(10)
    assert gate.accepts(10) is True
    assert gate.accepts(20) is False
    assert gate.cider_active is True
    gate.drop_client(10)
    assert gate.cider_active is False


def test_cider_match_rejects_different_track():
    gate = SourceGate()
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Other", artist="Artist"))
    assert gate.current_match(TrackMetadata("Song", "Artist")) is None
```

- [ ] **Step 2: Write failing receiver tick tests**

Add direct `_ingest` tests that do not require sockets:

```python
def test_closed_gate_rejects_tick_but_retains_full_frame():
    state = LyricsState()
    ticks = []
    state.time_ticked.connect(lambda current, playing: ticks.append((current, playing)))
    gate = SourceGate()
    gate.select_external()
    receiver = LyricsReceiver(state, gate=gate)

    assert receiver._ingest(json.dumps(FRAME), client_id=10) is True
    assert receiver._ingest(json.dumps({"reason": "tick", "currentTime": 3.0, "isPlaying": True}), client_id=10)
    assert state.snapshot.found is False
    assert ticks == []
    assert gate.current_match(TrackMetadata("Song", "X")) is not None
```

- [ ] **Step 3: Run gate and receiver tests and confirm failure**

Run:

```bash
uv run pytest tests/test_gate.py tests/test_receiver.py -q
```

Expected: FAIL because the gate has only a Boolean and `_ingest` has no client identity.

- [ ] **Step 4: Implement retained snapshots and binding in `SourceGate`**

Replace the Boolean-only API with compatible and explicit methods:

```python
@dataclass(frozen=True)
class CiderMatch:
    client_id: int
    snapshot: LyricsSnapshot


class SourceGate:
    def __init__(self) -> None:
        self._mode: Literal["standalone", "external", "cider"] = "standalone"
        self._bound_client_id: int | None = None
        self._snapshots: dict[int, tuple[int, LyricsSnapshot]] = {}
        self._sequence = 0

    @property
    def accept_ws(self) -> bool:
        return self._mode != "external"

    @property
    def cider_active(self) -> bool:
        return self._mode == "cider" and self._bound_client_id in self._snapshots

    def select_external(self) -> None:
        self._mode = "external"
        self._bound_client_id = None

    def select_cider(self, client_id: int) -> None:
        self._mode = "cider"
        self._bound_client_id = client_id

    def select_standalone(self) -> None:
        self._mode = "standalone"
        self._bound_client_id = None

    def observe_snapshot(self, client_id: int, snapshot: LyricsSnapshot) -> None:
        self._sequence += 1
        self._snapshots[client_id] = (self._sequence, snapshot)

    def current_match(self, track: TrackMetadata) -> CiderMatch | None:
        ordered = sorted(self._snapshots.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_sequence, snapshot) in ordered:
            if not snapshot.found or not snapshot.title:
                continue
            candidate = Candidate(
                song_id=snapshot.song_id or f"cider:{client_id}",
                title=snapshot.title,
                artist=snapshot.artist or "",
                duration_s=None,
            )
            evidence = evaluate_match(candidate, track)
            if evidence.confidence is MatchConfidence.HIGH:
                return CiderMatch(client_id, snapshot)
        return None

    def accepts(self, client_id: int) -> bool:
        if self._mode == "standalone":
            return True
        if self._mode == "external":
            return False
        return client_id == self._bound_client_id

    def drop_client(self, client_id: int) -> None:
        self._snapshots.pop(client_id, None)
        if self._bound_client_id == client_id:
            self.select_external()

    def set_accept_ws(self, value: bool) -> None:
        self.select_standalone() if value else self.select_external()
```

Keep `set_accept_ws()` temporarily as the compatibility wrapper shown above until Task 6 removes old calls.

- [ ] **Step 5: Pass client identity through the receiver**

Change `_ingest(raw_text, client_id=0)` so full frames are always parsed and retained before publication checks. Gate tick frames with the same `accepts(client_id)` decision. In `_handle_ws`, assign `client_id = id(ws)`, pass it to `_ingest`, and call `drop_client()` in `finally`.

```python
def _ingest(self, raw_text: str, *, client_id: int = 0) -> bool:
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError):
        return False
    if isinstance(payload, dict) and payload.get("reason") == "tick":
        if self._gate is None or self._gate.accepts(client_id):
            self._state.tick(_coerce_float(payload.get("currentTime")), _coerce_bool(payload.get("isPlaying")))
        return True

    snapshot = parse_payload(payload)
    if self._gate is not None:
        self._gate.observe_snapshot(client_id, snapshot)
        if not self._gate.accepts(client_id):
            return True
    self._state.update(snapshot)
    return True
```

- [ ] **Step 6: Run gate and receiver tests**

Run:

```bash
uv run pytest tests/test_gate.py tests/test_receiver.py -q
```

Expected: PASS. If the sandbox forbids loopback sockets, direct-ingest tests must pass and socket tests may require running outside the restricted sandbox.

- [ ] **Step 7: Commit Cider isolation**

```bash
git add src/kotonoha/providers/gate.py src/kotonoha/receiver.py tests/test_gate.py tests/test_receiver.py
git commit -m "fix(cider): isolate live source frames and ticks"
```

### Task 5: Resolve Providers In Exact Configured Order

**Files:**
- Create: `src/kotonoha/lyrics/resolver.py`
- Create: `tests/test_lyrics_resolver.py`

- [ ] **Step 1: Write failing exact-order tests**

Use fake cache/providers that append stage names to a shared list:

```python
TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)


def artifact(*, provider: str = "netease") -> LyricsArtifact:
    return LyricsArtifact(
        provider=provider,
        provider_song_id=f"{provider}-1",
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload={"lrc": "[00:01.00]line"},
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=MatchConfidence.HIGH,
    )


class FakeCache:
    def __init__(self, calls, hits):
        self.calls = calls
        self.hits = hits

    async def lookup(self, provider, _track, _parser):
        self.calls.append(f"cache:{provider}")
        return self.hits.get(provider)

    async def store(self, value):
        self.calls.append(f"store:{value.provider}")

    async def clear(self):
        self.calls.append("clear")


class FakeGate:
    def __init__(self, calls, match=None):
        self.calls = calls
        self.match = match

    def select_external(self):
        return None

    def current_match(self, _track):
        self.calls.append("cider")
        return self.match

    def select_cider(self, _client_id):
        return None


def resolver_with_fakes(
    calls,
    *,
    cache_hits=None,
    network_hits=None,
    cider_match=None,
    cache_enabled=True,
):
    cache_hits = cache_hits or {}
    network_hits = network_hits or {}

    def adapter(name):
        async def fetch(_session, _track):
            calls.append(f"network:{name}")
            return network_hits.get(name)

        return NetworkProvider(name=name, fetch=fetch, parse_payload=lambda _payload: ())

    return LyricsResolver(
        cache=FakeCache(calls, cache_hits),
        gate=FakeGate(calls, cider_match),
        providers={name: adapter(name) for name in ("netease", "lrclib")},
        cache_enabled=cache_enabled,
        negative_ttl=30.0,
    )


async def test_default_order_is_cache_network_per_provider_then_cider():
    calls = []
    resolver = resolver_with_fakes(
        calls,
        cache_hits={},
        network_hits={"lrclib": artifact(provider="lrclib")},
        cider_match=None,
    )

    result = await resolver.resolve(None, TRACK, ["netease", "lrclib", "cider"])

    assert result is not None and result.source == "lrclib"
    assert calls == [
        "cache:netease",
        "network:netease",
        "cache:lrclib",
        "network:lrclib",
        "store:lrclib",
    ]


async def test_cider_runs_at_configured_position_and_continues_when_unavailable():
    calls = []
    resolver = resolver_with_fakes(calls, cache_hits={}, network_hits={"netease": artifact()})
    await resolver.resolve(None, TRACK, ["lrclib", "cider", "netease"])
    assert calls == [
        "cache:lrclib",
        "network:lrclib",
        "cider",
        "cache:netease",
        "network:netease",
        "store:netease",
    ]


async def test_cache_disabled_skips_reads_and_writes():
    calls = []
    resolver = resolver_with_fakes(calls, cache_enabled=False, network_hits={"netease": artifact()})
    await resolver.resolve(None, TRACK, ["netease"])
    assert calls == ["network:netease"]
```

- [ ] **Step 2: Run resolver tests and confirm failure**

Run:

```bash
uv run pytest tests/test_lyrics_resolver.py -q
```

Expected: FAIL because `LyricsResolver` does not exist.

- [ ] **Step 3: Implement provider adapters and result types**

Create:

```python
@dataclass(frozen=True)
class ResolvedLyrics:
    source: str
    lines: tuple[LyricLine, ...] = ()
    live_snapshot: LyricsSnapshot | None = None
    cider_client_id: int | None = None


@dataclass(frozen=True)
class NetworkProvider:
    name: str
    fetch: Callable[[aiohttp.ClientSession, TrackMetadata], Awaitable[LyricsArtifact | None]]
    parse_payload: Callable[[Mapping[str, str]], tuple[LyricLine, ...]]
```

Register Netease and LRCLIB adapters. Inject the registry in tests.

- [ ] **Step 4: Implement exact stage order**

`resolve()` must call `gate.select_external()` before walking. For Cider, call `gate.current_match(track)`; if present, bind it and return `ResolvedLyrics(source="cider", live_snapshot=match.snapshot, cider_client_id=match.client_id)`, otherwise continue. For network providers, perform cache lookup then network fetch, store only high-confidence artifacts when enabled, and return the first usable result.

Implement the walk with this shape:

```python
async def _resolve_once(
    self,
    session: aiohttp.ClientSession,
    track: TrackMetadata,
    sources: tuple[str, ...],
) -> ResolvedLyrics | None:
    self._gate.select_external()
    for source in sources:
        if source == "cider":
            match = self._gate.current_match(track)
            if match is not None:
                self._gate.select_cider(match.client_id)
                return ResolvedLyrics(
                    source="cider",
                    live_snapshot=match.snapshot,
                    cider_client_id=match.client_id,
                )
            continue

        provider = self._providers.get(source)
        if provider is None:
            continue
        if self._cache_enabled:
            cached = await self._cache.lookup(source, track, provider.parse_payload)
            if cached is not None:
                return ResolvedLyrics(source=source, lines=cached.lines)

        negative_key = (source, track)
        if self._negative_until.get(negative_key, 0.0) > time.monotonic():
            continue
        try:
            artifact = await provider.fetch(session, track)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning("%s lyrics fetch failed: %s", source, exc)
            continue
        if artifact is None:
            self._negative_until[negative_key] = time.monotonic() + self._negative_ttl
            continue
        if self._cache_enabled and artifact.confidence is MatchConfidence.HIGH:
            await self._cache.store(artifact)
        return ResolvedLyrics(source=source, lines=artifact.lines)
    return None
```

- [ ] **Step 5: Add in-flight deduplication**

Key requests by normalized `TrackMetadata`, ordered source tuple, and `cache_enabled`. Await the same stored task directly and remove completed tasks in `finally`. This lets cancellation of the active MPRIS generation cancel the underlying network work instead of leaving a shielded stale request running.

```python
async def resolve(self, session, track, sources):
    ordered_sources = tuple(sources)
    key = (track, ordered_sources, self._cache_enabled)
    task = self._inflight.get(key)
    if task is None:
        task = asyncio.create_task(self._resolve_once(session, track, ordered_sources))
        self._inflight[key] = task
    try:
        return await task
    finally:
        if task.done() and self._inflight.get(key) is task:
            self._inflight.pop(key, None)

def set_cache_enabled(self, enabled: bool) -> None:
    self._cache_enabled = enabled
    self._negative_until.clear()

async def clear_cache(self) -> None:
    await self._cache.clear()
    self._negative_until.clear()
```

Add a memory-only `_negative_until: dict[tuple[str, TrackMetadata], float]`. Record a 30-second miss only when a provider returns no candidate normally; do not record network exceptions. Skip that provider's network call while the entry is live, and clear the dictionary when provider settings change.

- [ ] **Step 6: Run resolver tests**

Run:

```bash
uv run pytest tests/test_lyrics_resolver.py tests/test_lyrics_cache.py tests/test_gate.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit ordered resolution**

```bash
git add src/kotonoha/lyrics/resolver.py tests/test_lyrics_resolver.py
git commit -m "feat(lyrics): resolve providers in configured order"
```

### Task 6: Stabilize MPRIS Metadata And Cancel Obsolete Loads

**Files:**
- Create: `src/kotonoha/providers/mpris_track.py`
- Modify: `src/kotonoha/providers/mpris.py`
- Modify: `tests/test_mpris.py`
- Create: `tests/test_mpris_provider.py`

- [ ] **Step 1: Write failing pure stabilizer tests**

```python
def observation(track_id, title, artist, *, at):
    return TrackObservation(
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", 180.0, track_id),
        playback_status="Playing",
        position_s=0.0,
        observed_at=at,
    )


def test_empty_metadata_never_commits_and_same_track_id_can_recover():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/track/1", "", "", at=0.0)) is None
    assert stabilizer.observe(observation("/track/1", "Song", "Artist", at=0.2)) is None
    commit = stabilizer.observe(observation("/track/1", "Song", "Artist", at=0.6))
    assert commit is not None
    assert commit.info.title == "Song"


def test_new_title_old_artist_does_not_commit_before_stable_pair():
    stabilizer = TrackStabilizer()
    stabilizer.observe(observation("/old", "Old", "Old Artist", at=0.0))
    assert stabilizer.observe(observation("/new", "New", "Old Artist", at=1.0)) is None
    assert stabilizer.observe(observation("/new", "New", "New Artist", at=1.1)) is None
    commit = stabilizer.observe(observation("/new", "New", "New Artist", at=1.5))
    assert commit is not None
    assert commit.info.artist == "New Artist"


def test_missing_artist_commits_after_longer_window():
    stabilizer = TrackStabilizer()
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.0)) is None
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.5)) is None
    assert stabilizer.observe(observation("/1", "Instrumental", "", at=0.9)) is not None
```

- [ ] **Step 2: Write failing async provider tests**

Use fake player interfaces and a fake resolver:

```python
VALID_METADATA = {
    "xesam:title": "Song",
    "xesam:artist": ["Artist"],
    "xesam:album": "Album",
    "mpris:length": 180_000_000,
    "mpris:trackid": "/track/1",
}


class FakePlayer:
    def __init__(self, metadata, *, position_error=None):
        self.metadata = metadata
        self.position_error = position_error

    async def get_playback_status(self):
        return "Playing"

    async def get_metadata(self):
        return self.metadata

    async def get_position(self):
        if self.position_error is not None:
            raise self.position_error
        return 0


class RecordingResolver:
    def __init__(self):
        self.tracks = []

    async def resolve(self, _session, track, _sources):
        self.tracks.append(track)
        return None


class BlockingResolver(RecordingResolver):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.cancelled_generations = []

    async def resolve(self, _session, track, _sources):
        self.tracks.append(track)
        if track.title != "A":
            return None
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled_generations.append(1)
            raise


def track_commit(generation, title, artist):
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo(title, artist, "", 180.0, f"/{generation}"),
    )


async def test_position_failure_does_not_block_lyric_resolution():
    player = FakePlayer(metadata=VALID_METADATA, position_error=RuntimeError("unsupported"))
    resolver = RecordingResolver()
    provider = MprisProvider(LyricsState(), resolver=resolver, poll_interval=0.01)
    provider._session = object()

    async def active_player():
        return player, "org.mpris.MediaPlayer2.test"

    async def subscribed(_name):
        return None

    provider._active_player = active_player
    provider._ensure_subscribed = subscribed

    await provider._poll_once(now=0.0)
    await provider._poll_once(now=0.5)
    assert provider._load_task is not None
    await provider._load_task

    assert resolver.tracks[0].title == "Song"


async def test_new_generation_cancels_old_fetch():
    resolver = BlockingResolver()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver)
    provider._session = object()
    provider._schedule_load(track_commit(1, "A", "Artist A"))
    await resolver.started.wait()
    provider._schedule_load(track_commit(2, "B", "Artist B"))
    assert provider._load_task is not None
    await provider._load_task
    assert resolver.cancelled_generations == [1]
    assert state.snapshot.title == "B"


async def test_cider_disconnect_forces_ordered_resolution_again():
    resolver = RecordingResolver()
    gate = SourceGate()
    state = LyricsState()
    provider = MprisProvider(state, resolver=resolver, gate=gate)
    provider._current_commit = track_commit(1, "Song", "Artist")
    provider._content_owner = "cider"
    gate.observe_snapshot(10, LyricsSnapshot(found=True, title="Song", artist="Artist"))
    gate.select_cider(10)
    gate.drop_client(10)

    provider._ensure_content_owner()
    assert provider._load_task is not None
    await provider._load_task
    assert len(resolver.tracks) == 1
```

- [ ] **Step 3: Run MPRIS tests and confirm failure**

Run:

```bash
uv run pytest tests/test_mpris.py tests/test_mpris_provider.py -q
```

Expected: FAIL because stabilization and resolver injection do not exist.

- [ ] **Step 4: Move pure metadata logic to `mpris_track.py`**

Define and re-export through `mpris.py`:

```python
@dataclass(frozen=True)
class TrackInfo:
    title: str
    artist: str
    album: str
    length_s: float | None
    track_id: str

    def metadata(self) -> TrackMetadata:
        return TrackMetadata(self.title, self.artist, self.album, self.length_s)


@dataclass(frozen=True)
class TrackObservation:
    player_name: str
    info: TrackInfo
    playback_status: str
    position_s: float | None
    observed_at: float


@dataclass(frozen=True)
class TrackCommit:
    generation: int
    player_name: str
    info: TrackInfo


class TrackStabilizer:
    def __init__(self) -> None:
        self._candidate_key: tuple[object, ...] | None = None
        self._candidate: TrackObservation | None = None
        self._changed_at = 0.0
        self._committed_key: tuple[object, ...] | None = None
        self._generation = 0
        self._transitioning = False

    def observe(self, observation: TrackObservation) -> TrackCommit | None:
        info = observation.info
        if not info.title and not info.artist:
            self._transitioning = self._committed_key is not None
            self._candidate_key = None
            self._candidate = None
            return None

        key = (
            observation.player_name,
            info.track_id,
            info.title,
            info.artist,
            info.album,
            info.length_s,
        )
        if key != self._candidate_key:
            self._candidate_key = key
            self._candidate = observation
            self._changed_at = observation.observed_at
            self._transitioning = key != self._committed_key
            return None

        settle_seconds = 0.35 if info.artist else 0.8
        if observation.observed_at - self._changed_at < settle_seconds:
            return None
        if key == self._committed_key:
            self._transitioning = False
            return None

        self._committed_key = key
        self._generation += 1
        self._transitioning = False
        return TrackCommit(self._generation, observation.player_name, info)

    @property
    def transitioning(self) -> bool:
        return self._transitioning

    def reset(self) -> None:
        self._candidate_key = None
        self._candidate = None
        self._changed_at = 0.0
        self._committed_key = None
        self._transitioning = False
```

Use 0.35 seconds for complete metadata and 0.8 seconds when artist is missing. Empty title+artist observations can set transition state but never commit.

- [ ] **Step 5: Change signals to wake sampling instead of loading**

Add `self._poll_wakeup = asyncio.Event()`. `_on_props_changed()` should validate the interface and wake when `Metadata` is either present in `changed` or named in `invalidated`; it may log the signal but must not claim `_song_key` or create a load task.

Replace unconditional sleep in `_run()` with `asyncio.wait_for(self._poll_wakeup.wait(), timeout=self._poll_interval)`, clear the event, and poll once.

- [ ] **Step 6: Sample metadata independently from Position**

Read status and metadata for player selection. For the selected player, treat Position as optional:

Change the method signature to `async def _poll_once(self, *, now: float | None = None) -> None` and use `time.monotonic()` when `now` is `None`; deterministic tests pass explicit timestamps to the stabilizer.

```python
try:
    position = (await player.get_position()) / 1_000_000.0
except Exception as exc:  # D-Bus boundary; keep metadata path alive
    logger.debug("position read failed: %s", exc)
    position = None
```

Create the shared client session with `aiohttp.ClientTimeout(total=3.0, connect=1.5)` in `start()` so a failed provider cannot hold the ordered walk indefinitely.

When individual getters are used, read metadata again after Position and discard the observation if identity fields changed. Keep a current Playing player with empty metadata during the settling window, but prefer another Playing player with valid metadata over it. Never use Stopped/empty services as sorted-name fallback.

Track `_empty_since` separately in `MprisProvider`. Empty metadata never reaches the resolver. If the current player is Stopped/disappeared and the empty/no-player state lasts 0.35 seconds, call `_reset()`; if it remains Playing, continue polling without committing, searching, or writing a miss.

- [ ] **Step 7: Replace the load lock with one generation-owned task**

Add `_load_task`, `_load_tasks`, `_current_commit`, `_content_owner`, and `_provider_name`. `_schedule_load()` cancels obsolete work immediately, tracks every task for shutdown collection, then starts `_load_song(commit)`. Every post-await state change checks that `commit.generation` is still current.

Use a tracked task set so cancelled loads are collected during shutdown:

```python
def _schedule_load(self, commit: TrackCommit) -> None:
    if self._load_task is not None and not self._load_task.done():
        self._load_task.cancel()
    self._current_commit = commit
    task = asyncio.create_task(self._load_song(commit))
    self._load_task = task
    self._load_tasks.add(task)
    task.add_done_callback(self._load_tasks.discard)


async def _load_song(self, commit: TrackCommit) -> None:
    self._lines = []
    self._last_index = -2
    self._content_owner = "resolving"
    self._gate.select_external()
    self._state.update(
        build_snapshot(
            [],
            0.0,
            provider="MPRIS",
            song_id=None,
            title=commit.info.title,
            artist=commit.info.artist,
            is_playing=True,
        )
    )
    try:
        result = await self._resolver.resolve(
            self._session,
            commit.info.metadata(),
            self._lyrics_sources,
        )
    except asyncio.CancelledError:
        raise
    if self._current_commit != commit:
        return
    if result is None:
        self._content_owner = "none"
        return
    if result.source == "cider" and result.live_snapshot is not None:
        self._content_owner = "cider"
        self._provider_name = "cider"
        self._state.update(result.live_snapshot)
        return
    self._content_owner = "external"
    self._provider_name = result.source
    self._lines = list(result.lines)
```

In `stop()`, cancel every task in `_load_tasks` and await `asyncio.gather(*tasks, return_exceptions=True)` before closing the aiohttp session.

`_load_song()` calls `LyricsResolver.resolve()`. External results set lines/provider and keep the gate external. Cider results publish the retained snapshot and set owner `cider`. No result leaves an empty MPRIS title snapshot and keeps Cider closed unless Cider was actually selected.

- [ ] **Step 8: Keep clock/content ownership consistent**

In `_poll_once()`:

- suppress ticks while `TrackStabilizer.transitioning`;
- for external content, emit MPRIS ticks and build snapshots from local lines;
- for Cider content, do not emit MPRIS ticks or MPRIS empty snapshots;
- if Cider owned the track but `gate.cider_active` becomes false after disconnect, create a new generation and re-run the configured provider walk so later providers can take over;
- on no player after transition expiry, reset stabilizer/state and call `gate.select_standalone()`.

Set the snapshot provider to the actual selected source (`MPRIS:netease` or `MPRIS:lrclib`) instead of always `MPRIS:netease`.

Keep `set_lyrics_sources()` as a live setting: replace the source list, clear resolver memory-only misses, and force a new generation for the currently committed track. Add `set_cache_enabled()` and `clear_cache()` delegates used by Task 7.

- [ ] **Step 9: Run MPRIS, resolver, gate, and state tests**

Run:

```bash
uv run pytest tests/test_mpris.py tests/test_mpris_provider.py tests/test_lyrics_resolver.py tests/test_gate.py tests/test_state.py tests/test_select.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit MPRIS stabilization**

```bash
git add src/kotonoha/providers/mpris_track.py src/kotonoha/providers/mpris.py tests/test_mpris.py tests/test_mpris_provider.py
git commit -m "fix(mpris): stabilize metadata before lyric searches"
```

### Task 7: Add Cache Settings And Controller Wiring

**Files:**
- Modify: `src/kotonoha/config.py`
- Modify: `src/kotonoha/settings_dialog.py`
- Modify: `src/kotonoha/controller.py`
- Modify: `src/kotonoha/strings.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_strings.py`
- Create: `tests/test_settings_dialog.py`

- [ ] **Step 1: Write failing config tests**

```python
def test_cache_enabled_defaults_true_and_roundtrips(tmp_path):
    assert Config().cache_enabled is True
    path = tmp_path / "config.json"
    save_config(Config(cache_enabled=False), path)
    assert load_config(path).cache_enabled is False


def test_cache_enabled_is_clamped_to_bool():
    assert Config(cache_enabled=0).clamped().cache_enabled is False
    assert Config(cache_enabled=1).clamped().cache_enabled is True
```

- [ ] **Step 2: Run config tests and confirm failure**

Run:

```bash
uv run pytest tests/test_config.py -q
```

Expected: FAIL because `Config.cache_enabled` does not exist.

- [ ] **Step 3: Add configuration and localized strings**

Add `cache_enabled: bool = True` next to `lyrics_sources`, include it in `clamped()`, and add complete `en`, `zh-Hans`, `zh-Hant`, and `ja` strings:

```python
"set.cache_enabled": {
    "en": "Enable local lyrics cache",
    "zh-Hans": "启用本地歌词缓存",
    "zh-Hant": "啟用本地歌詞快取",
    "ja": "ローカル歌詞キャッシュを有効化",
},
"btn.clear_cache": {
    "en": "Clear lyrics cache",
    "zh-Hans": "清除歌词缓存",
    "zh-Hant": "清除歌詞快取",
    "ja": "歌詞キャッシュを消去",
},
```

- [ ] **Step 4: Add settings controls without touching overlay rendering**

Add `clear_cache_requested = pyqtSignal()` to `SettingsDialog`. In `_sources_tab()`, place a checked `QCheckBox` and a `QPushButton` below the provider list. Connect the button through a zero-argument lambda to `clear_cache_requested.emit`. Include `cache_enabled=self._cache_enabled.isChecked()` in `current_config()`.

Use these exact attribute names so the focused UI test can inspect them:

```python
self._cache_enabled = QCheckBox(t("set.cache_enabled"))
self._cache_enabled.setChecked(self._config.cache_enabled)
layout.addWidget(self._cache_enabled)

self._clear_cache = QPushButton(t("btn.clear_cache"))
self._clear_cache.clicked.connect(lambda _checked=False: self.clear_cache_requested.emit())
layout.addWidget(self._clear_cache)
```

- [ ] **Step 5: Wire setting updates and clear action**

Expose these methods on `MprisProvider` as thin resolver delegates:

```python
def set_cache_enabled(self, enabled: bool) -> None:
    self._resolver.set_cache_enabled(enabled)


async def clear_cache(self) -> None:
    await self._resolver.clear_cache()
```

In `AppController._open_settings()`, connect `clear_cache_requested` to a new `_clear_lyrics_cache()` method that creates an asyncio task and logs failures in a done callback. In `_apply_config()`, call `self._mpris.set_cache_enabled(config.cache_enabled)`.

```python
def _clear_lyrics_cache(self) -> None:
    task = asyncio.create_task(self._mpris.clear_cache())

    def finished(done: asyncio.Task[None]) -> None:
        try:
            done.result()
        except asyncio.CancelledError:
            return
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Could not clear lyrics cache: %s", exc)

    task.add_done_callback(finished)
```

Import `asyncio` and `sqlite3` in `controller.py`. Connect the signal before showing the dialog.

- [ ] **Step 6: Add an offscreen settings control test**

Create `tests/test_settings_dialog.py`:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from kotonoha.config import Config
from kotonoha.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_cache_controls_roundtrip_and_clear_signal(qapp):
    dialog = SettingsDialog(Config(cache_enabled=False))
    emitted = []
    dialog.clear_cache_requested.connect(lambda: emitted.append(True))

    assert dialog._cache_enabled.isChecked() is False
    dialog._cache_enabled.setChecked(True)
    assert dialog.current_config().cache_enabled is True
    dialog._clear_cache.click()
    assert emitted == [True]
    dialog.close()
```

- [ ] **Step 7: Run configuration, string, and settings tests**

Run:

```bash
uv run pytest tests/test_config.py tests/test_strings.py tests/test_settings_dialog.py -q
```

Expected: PASS, including the existing assertion that every string has all four languages.

- [ ] **Step 8: Run import and focused controller checks**

Run:

```bash
uv run python -c "from kotonoha.config import Config; from kotonoha.settings_dialog import SettingsDialog; assert Config().cache_enabled"
uv run pytest tests/test_gate.py tests/test_lyrics_resolver.py tests/test_mpris_provider.py -q
```

Expected: imports succeed and tests PASS. Do not open a GUI window.

- [ ] **Step 9: Commit settings**

```bash
git add src/kotonoha/config.py src/kotonoha/settings_dialog.py src/kotonoha/controller.py src/kotonoha/strings.py tests/test_config.py tests/test_strings.py tests/test_settings_dialog.py
git commit -m "feat(settings): add local lyrics cache controls"
```

### Task 8: Document Behavior And Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/SPEC-mpris-lyrics.md`

- [ ] **Step 1: Update user documentation**

Document the exact example sequence:

```text
netease -> lrclib -> cider

1. local Netease cache
2. network Netease
3. local LRCLIB cache
4. network LRCLIB
5. current Cider live snapshot, when available
```

State that changing provider order moves each provider's cache/network stage together, cache can be disabled or cleared, empty transitional MPRIS metadata is ignored, and Cider is attempted at its configured position.

- [ ] **Step 2: Run Python tests**

Run:

```bash
uv run pytest
```

Expected: all Python tests PASS. If restricted sandbox networking blocks aiohttp loopback tests, rerun the same command with the required sandbox permission rather than accepting failures.

- [ ] **Step 3: Run lint and type checking**

Run:

```bash
uv run ruff check .
uv run ty check
```

Expected: both commands exit 0.

- [ ] **Step 4: Run Cider regression tests without changing plugin code**

Run:

```bash
cd plugins/cider/lyrics
pnpm test
```

Expected: existing Vitest suite PASS. If dependencies are absent, run `pnpm install` with network approval, then rerun `pnpm test`.

- [ ] **Step 5: Verify protected GUI files are untouched**

Run:

```bash
git diff --name-only d3ffb24..HEAD -- src/kotonoha/overlay.py src/kotonoha/karaoke_label.py src/kotonoha/karaoke.py src/kotonoha/native.py src/kotonoha/layer_shell_bridge.cpp plugins/cider/lyrics/src
```

Expected: no output.

- [ ] **Step 6: Inspect final status and commit documentation**

```bash
git status --short
git add README.md docs/SPEC-mpris-lyrics.md
git commit -m "docs: describe ordered lyric cache resolution"
```

Expected: only intentional changes are committed; generated caches, databases, and build output remain untracked/ignored.
