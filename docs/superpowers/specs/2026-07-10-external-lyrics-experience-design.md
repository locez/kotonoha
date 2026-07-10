# External Lyrics Experience Optimization Design

## Context

Kotonoha currently combines two different lyric paths:

- Netease and LRCLIB return full timed lyric documents. MPRIS position selects the current line locally.
- The Cider plugin pushes playback-projected lyric snapshots and high-frequency ticks over WebSocket.

The existing architecture is directionally correct, but several small boundary problems reduce real-world reliability:

- MPRIS metadata changes can trigger a search before title, artist, duration, and position belong to the same track.
- An obsolete lyric request can hold the load lock and delay the current track.
- Search normalization and candidate scoring can accept the wrong version or even a different song with a similar duration.
- Fallback requests are repeated after restarts even when the same provider result was already fetched.
- Cider ticks can currently reach the shared clock while an external provider owns the lyrics.

This work focuses on making external lyrics reliable and fast enough that Cider is an optional final fallback, not the preferred path.

## Goals

1. Prevent mixed MPRIS metadata from starting searches such as a new title combined with the previous artist.
2. Improve Netease and LRCLIB search recall without accepting low-confidence or wrong-version matches.
3. Reduce cold fallback latency and eliminate repeated searches for previously fetched lyrics.
4. Preserve the configured provider order exactly.
5. Keep Cider available as a live fallback while preventing it from interfering with an external lyric source.
6. Leave the HUD renderer, karaoke widgets, layer-shell bridge, and overlay geometry unchanged.

## Non-Goals

- Do not change the Cider plugin protocol or make it push a full lyric document.
- Do not redesign the Qt bridge, overlay, karaoke rendering, or media clock.
- Do not make Cider a preferred source based on the current player identity.
- Do not add a global cache provider ahead of configured providers.
- Do not issue speculative network requests to lower-priority providers.
- Do not persist negative search results to disk.

## Considered Approaches

### 1. Patch individual symptoms

Add a short debounce, fix the `feat.` regex, and add a dictionary cache inside `MprisProvider`.

This has the smallest diff, but metadata ownership, cancellation, provider order, and persistent cache behavior would remain implicit and difficult to test.

### 2. Focused data-path hardening

Add a pure metadata stabilizer, a cancellable track generation, a provider-order resolver, shared matching logic, and a provider-scoped SQLite cache.

This is the selected approach. It fixes the observed boundaries while keeping the existing state and GUI contracts intact.

### 3. Full provider coordinator rewrite

Replace MPRIS, Cider arbitration, state updates, and source selection with a new coordinator.

This would be a larger behavioral rewrite than the current problems justify and would increase risk around the working HUD path.

## Architecture

```text
MPRIS signal/poll
      |
      v
TrackObservation -> MetadataStabilizer -> committed TrackIdentity + generation
                                              |
                                              v
                                      LyricsResolver
                                              |
                  +---------------------------+---------------------------+
                  |                           |                           |
             Netease stage               LRCLIB stage              Cider fallback
          cache -> network             cache -> network             existing WS gate
                  |                           |                           |
                  +---------------------------+---------------------------+
                                              |
                                              v
                                      LyricsState snapshot/tick
                                              |
                                              v
                                      Existing Qt HUD unchanged
```

The selected provider owns both lyric content and clock calibration:

- External provider selected: full lyrics are selected with MPRIS position; Cider snapshots and ticks are rejected.
- Cider selected after earlier providers miss: the existing Cider snapshot and tick behavior is preserved.
- No usable MPRIS track: the existing standalone Cider behavior remains available.

## Stable Track Observation

### Track identity

Introduce a small immutable `TrackIdentity` containing:

- player bus name;
- MPRIS track ID when present;
- raw title, artist list/string, album, and duration;
- normalized title and artist tokens used for comparison;
- a monotonically increasing generation assigned after stabilization.

The player name and duration are part of the committed identity so switching between players or receiving a delayed duration update can trigger a correct re-resolution.

### Signal behavior

`PropertiesChanged` must not call the network loader directly. It records the newest metadata candidate and wakes the provider loop. The loop obtains a complete logical sample and feeds it to the stabilizer.

When individual property getters are required, metadata is read before and after status/position. If the identity fields changed between the reads, the sample is discarded. When supported, `org.freedesktop.DBus.Properties.GetAll` may be used as the primary sample path, with the current getters retained as compatibility fallback.

### Stabilization rule

- A candidate must have a non-empty title.
- Identity-field changes restart a 350 ms settling window.
- Repeated identical observations do not restart the window.
- Metadata with a missing artist may commit after 800 ms so players that permanently omit artists still work.
- During an uncommitted transition, old lyric ticks and content updates are suppressed so a new position cannot drive the previous song's lyrics.

These values are implementation constants covered by deterministic tests, not user-facing settings.

### Cancellable loading

Each committed track receives a generation and at most one `_load_task`.

- A newer generation cancels the previous task immediately.
- No obsolete request waits in a serial load lock.
- Every state or gate commit verifies that its generation is still current.
- Provider shutdown cancels and awaits both the polling task and active load task.

## Search Normalization And Matching

### Normalization

Use one shared normalization module for remote candidates and local cache candidates:

- Unicode NFKC normalization and `casefold()`;
- normalized whitespace and punctuation;
- safe `feat.`, `ft.`, and `featuring` boundaries that do not damage names such as `Feather` or `FTISLAND`;
- artist tokenization that tolerates ordering and common separators;
- extraction of version qualifiers such as live, remix, remaster, acoustic, instrumental, demo, sped-up, and slowed variants;
- raw values are preserved for display and provider requests.

No Simplified/Traditional Chinese conversion dependency is added. Cross-script cases require supporting artist, album, or duration evidence.

### Query variants

Each network provider attempts at most two staged queries:

1. raw title plus full artist metadata;
2. base title plus primary artist when the first query has no confident candidate.

Title-only search is allowed only when the player provides no usable artist. Results from query variants are deduplicated by provider song ID.

### Acceptance rules

Duration is evidence, never sufficient by itself.

A persisted or displayed candidate must meet these rules:

- the normalized base title is an exact or strong match, or a cross-script mismatch is compensated by strong artist plus album/duration evidence;
- at least one primary artist matches when both sides provide artists;
- duration differs by no more than 3 seconds for high confidence, or by no more than 8 seconds when title and artist evidence is otherwise exact;
- explicit version qualifiers do not conflict;
- short substring matches such as `A` against `ABC` are rejected.

The matcher returns structured evidence and a confidence class rather than relying only on an opaque numeric score. Only high-confidence results are persisted.

### Provider-specific corrections

Netease:

- validate response status and shape;
- ignore entries without a usable provider song ID;
- if a non-empty YRC payload parses to no lyric lines, fall back to LRC;
- include album metadata when the API response provides it.

LRCLIB:

- preserve the exact `/api/get` attempt;
- map `/api/search` results to candidates and rank them with the shared matcher instead of taking the first synced lyric;
- keep `/get` and `/search` failures isolated so one failed request does not suppress the other stage;
- use LRCLIB result ID and metadata when available.

## Provider Order And Cache Semantics

The local cache is not an independent provider. It is the first lookup tier inside each cacheable provider.

For this configured order:

```text
netease -> lrclib -> cider
```

the exact execution order is:

```text
1. local Netease cache
2. network Netease
3. local LRCLIB cache
4. network LRCLIB
5. existing Cider live fallback
```

Changing the provider order changes the local and network stages together. A cached lower-priority provider must never outrank a higher-priority provider's network result.

The resolver therefore follows this contract:

```python
for provider in configured_providers:
    if cache_enabled and provider.cacheable:
        cached = cache.find(provider.name, track)
        if cached is a high-confidence match:
            return cached

    fetched = await provider.fetch(track)
    if fetched is a high-confidence match:
        if cache_enabled and provider.cacheable:
            cache.store(provider.name, fetched)
        return fetched

    if provider is the live Cider source:
        hand off through the existing gate
```

Network providers are attempted strictly in order. There is no cross-provider hedging or prefetching.

## Persistent Cache

### Storage

Use the Python standard library `sqlite3` under:

```text
$XDG_CACHE_HOME/kotonoha/lyrics.sqlite3
```

with `~/.cache` as the XDG fallback. No new runtime dependency is required.

The primary identity of a cached lyric artifact is:

```text
provider + provider_song_id
```

When a provider has no stable ID, use a content hash scoped to that provider.

The cache stores:

- provider and provider song ID;
- provider-returned title, artists, album, duration, and version qualifiers;
- raw timed lyric payload needed to parse the result again;
- fetch and last-access timestamps;
- cache schema, parser, and normalizer versions.

There is no persistent MPRIS track ID mapping, player mapping, or search-string-to-result mapping. On playback, the current stable MPRIS metadata is matched directly against candidates from the selected provider's local cache.

Provider artifacts may be stored only after a high-confidence network match and successful lyric parse. A local entry must pass the current matcher again before reuse.

### Lifecycle

- `cache_enabled` defaults to `true`.
- Disabling the cache skips disk reads and writes but does not delete existing entries.
- Clearing the cache removes the SQLite data without changing provider configuration.
- Keep at most 1,000 lyric artifacts and remove least-recently-used entries above the limit.
- Cache corruption or an unparseable entry invalidates that entry and continues with the same provider's network stage.
- Negative results remain memory-only with a short lifetime; temporary network failures are never persisted.

### Settings

Add to the existing source settings:

- an `Enable local lyrics cache` checkbox;
- a `Clear local lyrics cache` command;

Provider reordering continues to list only Netease, LRCLIB, and Cider. The cache is not displayed as a provider.

This touches the settings dialog and configuration model only. It does not change overlay rendering or the layer-shell bridge.

## Cider Isolation

The Cider TypeScript plugin and WebSocket payload remain unchanged.

Python-side arbitration receives only narrow corrections:

- close the Cider gate as soon as a stable MPRIS track enters external resolution;
- keep it closed after an external cache or network hit;
- reject Cider tick frames whenever the gate rejects Cider lyric frames;
- restore the gate only when the configured provider walk actually reaches the Cider fallback, or when no usable MPRIS track exists;
- prevent MPRIS empty snapshots from overwriting a selected Cider snapshot.

Improving Cider player identification, changing its payload shape, or making it provide complete lyrics is deferred.

## Fetch Speed

Cold requests remain strictly ordered, so speed improvements come from correctness and eliminating repeated work:

- do not send searches for unstable or mixed metadata;
- cancel stale track requests immediately;
- reuse persistent high-confidence results;
- deduplicate identical in-flight requests within the process;
- use a bounded per-request timeout so a failed provider reaches the next stage;
- stop query variants as soon as a confident candidate is found;
- reuse the existing shared `aiohttp.ClientSession`.

The initial total timeout target is 3 seconds per network provider, with connection errors falling through immediately. Timeout constants remain internal and can be tuned after live measurements.

## Error Handling And Observability

- Network, JSON, and provider-shape failures are logged with provider and stable track generation.
- Cancellation is normal control flow and must not be logged as an error.
- Verbose logs record metadata candidate changes, committed identities, cache hit/miss, query variants, selected provider, confidence evidence, and stale-result drops.
- Logs must not include complete lyric payloads.
- A cache failure never blocks the corresponding network provider.
- A provider failure never prevents later configured providers from being attempted.

## Testing

### Pure Python tests

- metadata stabilization for new-title/old-artist, old-title/new-artist, missing artist, repeated identical signals, and player switches;
- normalization for Unicode width, composed/decomposed accents, safe `feat.` handling, artist ordering, and version qualifiers;
- candidate acceptance for duration-only false matches, short titles, live/remix conflicts, cross-script titles, album evidence, and duration boundaries;
- exact provider-stage ordering with cache enabled and disabled;
- SQLite lookup scoped by provider, LRU pruning, clear behavior, corrupt entries, and schema versions.

### Async provider tests

- signal arrival wakes sampling but does not fetch immediately;
- A -> B -> C transitions cancel obsolete loads;
- an obsolete result cannot update state or the Cider gate;
- Netease and LRCLIB response/fallback paths use recorded fixtures or mocks;
- in-flight requests for the same committed identity are deduplicated;
- Cider full frames and ticks are rejected while an external provider owns the track.

### Configuration and UI tests

- cache option defaults, round trip, and clamping;
- clear-cache service behavior without exercising overlay rendering;
- existing provider reorder behavior remains unchanged.

### Validation

Run:

```text
uv run pytest
uv run ruff check .
uv run ty check
cd plugins/cider/lyrics && pnpm test
```

The Cider test suite is regression validation only because the plugin code is out of scope.

## Delivery Boundaries

Expected implementation files are limited to the MPRIS provider, lyrics matching/fetching modules, cache/resolver modules, configuration, settings, and focused tests.

Do not modify:

- `src/kotonoha/overlay.py`;
- `src/kotonoha/karaoke_label.py`;
- `src/kotonoha/karaoke.py`;
- `src/kotonoha/native.py`;
- `src/kotonoha/layer_shell_bridge.cpp`;
- the Cider TypeScript plugin, unless a separate future design explicitly approves it.
