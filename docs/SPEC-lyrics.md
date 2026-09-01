# Lyrics, Cache, and Manual Selection

[中文](SPEC-lyrics.zh-CN.md)

This document defines the models and behavior boundaries for lyric sources, parsing, the SQLite cache, and manual lyric selection.

## Domain model

- `TrackIdentity` and `PlaybackObservation` are normalized playback facts emitted by player adapters.
- `TrackMetadata` is provider-neutral metadata used for matching and search.
- `LyricsArtifact` contains provider identity, the original payload, the parsed lyric document, and match confidence.
- `LyricsDocument` is a complete timed document. The display layer derives the current line, context, word progress, and interlude state from it.
- `LyricsSourceResult` carries the source id, document, match confidence, duration, cache artifact, and source kind for one resolution result.

## Source catalog

| Kind | Sources | Capability |
| --- | --- | --- |
| `local` | Sidecar, embedded | Exact hints supplied by the player |
| `network` | Netease, QQ Music, LRCLIB, Kugou | Metadata search or exact song-id lookup |
| `live` | Cider HTTP, generic adapter | Candidate document for the active player track |

The default lyric source order is:

```text
netease -> lrclib -> kugou -> cider
```

`lyrics_sources` controls lyric providers. `display_sources` (default
`mpris -> cider -> adapter`) controls playback facts and live lyric candidates;
the two lists have separate responsibilities. QQ Music supports exact song-id
lookup only. Cider exposes the active player track only. Neither provides
metadata-based manual search, so the search service returns a typed unavailable
reason for them.

## Resolution policy

The LRC parser accepts both standard line timestamps and Enhanced LRC inline
`<mm:ss.xx>` timestamps. Inline timestamps are normalized into `LyricWord`; input
without inline timestamps remains line-timed. A word ends at the next inline
timestamp, or at the line end when it is the final segment.

Each stable MPRIS track starts a new generation. Tasks from an older generation
are cancelled, and stale results cannot update the active display.

Automatic resolution follows this order:

1. An exact-hint path checks a matching `MANUAL` cache entry, then the source named by the hint.
2. A normal source plan checks `MANUAL` cache entries that match the current track.
3. With `prefer_best_lyrics` enabled, candidates compete by match confidence and configured order breaks ties. With it disabled, the first valid result in configured order wins.
4. An `AUTO` cache entry is considered only for its owning provider. A network failure is not treated as a cache miss.

## SQLite cache

`LyricsCache` is an asynchronous facade. `LyricsCacheStorage` runs synchronous
SQLite operations through its injected worker. The default database is
`$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3`, with schema version `1` and a default
limit of `1000` entries. Old entries are evicted by `last_accessed`.

The record key is `(provider, provider_song_id)`. A record stores provider
metadata, the original payload, timestamps, selection mode, and version data.
Corrupt payloads and payloads without timed lines are deleted and treated as
cache misses.

| Mode | Meaning |
| --- | --- |
| `AUTO` (`auto`) | Written by high-confidence automatic resolution and used only by its provider |
| `MANUAL` (`manual`) | Confirmed by the user and checked before ordinary resolution and exact hints |

The cache facade exposes these operations:

| Operation | Use |
| --- | --- |
| `search(query)` | Fuzzy metadata search over title, artist, album, provider, and song id; ordered by recent use |
| `get(key)`, `count()` | Read one metadata record or the total count |
| `upsert(artifact, mode)` | Create or replace a record |
| `update(key, artifact, mode)` | Update an existing record for lyric workflows; not exposed as an edit action in cache management |
| `delete(key)`, `delete_many(keys)`, `clear()` | Delete one record, several records, or all records |
| `lookup()`, `lookup_manual()` | Content lookup used by the resolver |

The cache-management window uses metadata search and deletion only. It shares
the `LyricsCache` instance with resolution through narrow management and write
ports; it does not depend on the MPRIS facade.

## Manual search and application

The overlay search button opens a modeless search window. Title, artist, and
album are prefilled and editable. The current duration is read-only context.

The search service queries the selected providers concurrently. Each provider
contributes at most `30` candidates, and one search exposes at most `90` results
to the UI. Results are deduplicated by `provider:provider_song_id`. Each result
contains provider, track metadata, duration, lyric format, translation
availability, match confidence, and the complete artifact. Unsupported sources
return a typed result containing the source and reason.

Applying a result follows this sequence:

1. Write the artifact to the shared cache with `MANUAL` mode.
2. Call `DisplayCoordinator.apply_manual_artifact()`.
3. Replace the document only if the active track still matches the track used for the search.
4. Re-project at the current playback position immediately; playback does not need to reach the next track.
5. Refresh the search window's source status.

The search window reports four independent facts: lyric provider, acquisition
method, playback source (`MPRIS`, `Cider`, or `adapter`), and cache state (none,
automatic cache, or manual selection). A track change clears the manual display
override, and the new track follows the configured source policy.

## Local sources and failures

Sidecar and embedded lyrics are read by the local worker and are not written to
the network cache. Their origins are `sidecar` and `embedded` respectively.

Transport, parsing, and payload failures are converted to narrow exceptions or
typed unavailable results at provider boundaries. Cache failures raise
`LyricsCacheError`; an unsuccessful cache operation is never reported as a
successful one.
