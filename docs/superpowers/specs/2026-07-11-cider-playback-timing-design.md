# Cider Playback Timing Compatibility Design

## Context

Direct Chrome DevTools Protocol sampling of the running Cider page showed two boundary failures:

- MusicKit reported the correct song-relative position and duration, while Chromium exported an infinite media duration as the MPRIS `int64` maximum sentinel.
- Current Cider stores playback state under `CiderApp.musicKitStore.player`, while the plugin reads fields directly from `musicKitStore`. Its full frames therefore contain a null playback item and its high-frequency tick loop has no usable time to send.

These failures affect lyric lookup and clock calibration, but they do not require changes to the Qt bridge or HUD renderer.

## Goals

1. Restore Cider plugin metadata, position, duration, and playing-state probes across current and older Cider layouts.
2. Keep the high-frequency WebSocket tick active when MusicKit has a valid playback clock.
3. Treat unusable MPRIS lengths as unknown so they cannot distort lyric matching.
4. Preserve provider ordering, Cider gate behavior, receiver protocol, and all GUI behavior.

## Non-Goals

- Do not make Cider a mandatory fallback or change its configured provider position.
- Do not change lyric source selection, cache semantics, search scoring, or network timeouts.
- Do not alter Qt, QML, overlay geometry, karaoke rendering, or the Qt bridge.
- Do not add a remote-debugging dependency to normal operation.

## Considered Approaches

### Patch only the current Cider path

Read `CiderApp.musicKitStore.player` directly everywhere. This fixes the observed version but would regress older Cider and PluginKit layouts already supported by the project.

### Resolve playback sources with compatible fallbacks

Use the PluginKit store when it exposes playback fields, then current Cider's nested `musicKitStore.player`, then legacy Cider stores. Use MusicKit as an independent fallback for time, duration, playing state, and now-playing metadata.

This is the selected approach. It is small, testable, and preserves the existing protocol.

### Consume Cider's internal `CU:Playback` WebSocket

This event currently contains correct playback data, but coupling the plugin to an internal transport event is more fragile than reading the public MusicKit object and Cider store state already present in the page.

## Design

### Cider probe

The playback probe will resolve three independent sources instead of assuming one store owns every field:

1. A store/player object for Cider-specific state and metadata.
2. `MusicKit.getInstance()` for stable song-relative playback values and now-playing metadata.
3. An HTML media element only when Cider or PluginKit explicitly exposes it.

For current Cider, `musicKitStore.player` must be checked before the legacy `musicKitStore` object. Existing PluginKit direct-store behavior remains supported.

The lightweight tick returns the first finite song-relative time from an explicitly exposed audio element, MusicKit, or the resolved player, in that order. This preserves the existing high-precision audio path while avoiding repeated calibration against current Cider's lower-frequency player-store updates. Playing state follows the same source order. A valid time is sufficient to send a tick; an unavailable playing state remains `null` and the Python receiver retains its current compatibility behavior.

The full playback snapshot uses resolved player values with MusicKit fallbacks for `nowPlayingItem`, `isPlaying`, and `currentPlaybackTime`. `audioDuration` remains tied to an actual finite media duration; MusicKit duration is not mislabeled as an audio-element duration.

### MPRIS duration parsing

Duration parsing remains owned by `mpris_track.parse_metadata`. It accepts finite, positive microsecond values up to 24 hours and converts them to seconds. Boolean values, non-finite numbers, non-positive values, the MPRIS/Chromium unknown sentinel, and values above 24 hours become `None`.

Unknown duration is intentionally preserved as absence of evidence. Provider matching continues to rely on title, artist, and album rather than comparing candidates against a fabricated duration.

## Testing

TypeScript tests will reproduce the current Cider layout and verify both full snapshots and lightweight ticks. Existing PluginKit and legacy-store tests must continue to pass.

Python tests will cover finite duration conversion plus non-finite, non-positive, sentinel, and implausibly large values. Focused suites run before full Python and Cider plugin suites.

Runtime verification will confirm that a Cider tick contains a finite current time and that the running MPRIS sentinel is parsed as unknown. No visual regression test is required because GUI code is unchanged.
