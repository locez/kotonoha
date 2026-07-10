# Cider Playback Timing Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore valid Cider playback frames and prevent invalid MPRIS durations from degrading external lyric matching without touching the GUI.

**Architecture:** Keep playback compatibility inside the pure TypeScript probe by resolving current and legacy Cider player layouts plus MusicKit fallbacks. Keep MPRIS duration validation inside the pure Python metadata parser so every downstream resolver receives either a credible duration or `None`.

**Tech Stack:** TypeScript, Vitest, Python 3.10+, pytest, Ruff, ty, pnpm/Vite

---

### Task 1: Restore Current Cider Playback Probing

**Files:**
- Modify: `plugins/cider/lyrics/src/__tests__/playback.test.ts`
- Modify: `plugins/cider/lyrics/src/probe/playback.ts`
- Modify: `plugins/cider/lyrics/src/probe/types.ts`

- [ ] **Step 1: Add failing tests for the current nested player and MusicKit tick**

Update the import and add these focused cases:

```ts
import { probePlayback, probePlaybackTime } from "../probe/playback";

it("reads the current Cider nested player layout", () => {
  const nowPlayingItem = { attributes: { name: "Current Song" } };
  const globals = {
    CiderApp: {
      musicKitStore: {
        player: {
          nowPlayingItem,
          isPlaying: true,
          currentPlaybackTime: 41,
          currentPlaybackDuration: 180,
        },
      },
    },
    MusicKit: {
      getInstance: () => ({
        nowPlayingItem,
        isPlaying: true,
        currentPlaybackTime: 42.5,
        currentPlaybackDuration: 180,
      }),
    },
  };

  expect(probePlayback(globals)).toMatchObject({
    nowPlayingItem,
    isPlaying: true,
    currentPlaybackTime: 41,
    currentPlaybackDuration: 180,
  });
});

it("uses MusicKit for a high-frequency tick when Cider exposes no audio element", () => {
  const globals = {
    CiderApp: {
      musicKitStore: {
        player: {
          isPlaying: true,
          currentPlaybackTime: 41,
        },
      },
    },
    MusicKit: {
      getInstance: () => ({
        isPlaying: true,
        currentPlaybackTime: 42.5,
      }),
    },
  };

  expect(probePlaybackTime(globals)).toEqual({
    currentTime: 42.5,
    isPlaying: true,
  });
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd plugins/cider/lyrics
pnpm exec vitest run src/__tests__/playback.test.ts
```

Expected: FAIL because the current implementation chooses `musicKitStore` instead of `musicKitStore.player`, does not export `currentPlaybackDuration`, and returns a null high-frequency time.

- [ ] **Step 3: Implement compatible player and MusicKit resolution**

In `plugins/cider/lyrics/src/probe/types.ts`, add the optional full-frame duration:

```ts
export type PlaybackProbe = {
  nowPlayingItem: unknown;
  isPlaying?: boolean;
  currentPlaybackTime?: number;
  currentPlaybackDuration?: number;
  audioCurrentTime?: number;
  audioDuration?: number;
};
```

In `plugins/cider/lyrics/src/probe/playback.ts`:

```ts
type CiderGlobals = {
  CiderApp?: any;
  __PLUGINSYS__?: any;
  MusicKit?: any;
};

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function hasPlaybackState(value: any): boolean {
  return Boolean(
    value && (
      value.nowPlayingItem != null ||
      numberOrUndefined(value.currentPlaybackTime ?? value.playbackTime) !== undefined ||
      typeof value.isPlaying === "boolean" ||
      value.audioElement
    )
  );
}

function playbackPlayer(globals: CiderGlobals): any {
  const pluginStore = globals.__PLUGINSYS__?.Stores?.appleMusicStore;
  if (hasPlaybackState(pluginStore)) {
    return pluginStore;
  }
  const musicKitStore = globals.CiderApp?.musicKitStore;
  if (hasPlaybackState(musicKitStore?.player)) {
    return musicKitStore.player;
  }
  if (hasPlaybackState(musicKitStore)) {
    return musicKitStore;
  }
  return globals.CiderApp?.store;
}

function musicKit(globals: CiderGlobals): any {
  return globals.MusicKit?.getInstance?.();
}

function audioElement(globals: CiderGlobals, player: any): any {
  return player?.audioElement ?? globals.CiderApp?.musicKitStore?.audioElement;
}
```

Use those helpers to implement the two public probes:

```ts
export function probePlaybackTime(globals: CiderGlobals): {
  currentTime: number | null;
  isPlaying: boolean | null;
} {
  const player = playbackPlayer(globals);
  const instance = musicKit(globals);
  const audio = audioElement(globals, player);
  const audioPlaying = typeof audio?.paused === "boolean" ? !audio.paused : undefined;

  return {
    currentTime:
      numberOrUndefined(audio?.currentTime) ??
      numberOrUndefined(instance?.currentPlaybackTime) ??
      numberOrUndefined(player?.currentPlaybackTime ?? player?.playbackTime) ??
      null,
    isPlaying:
      audioPlaying ??
      booleanOrUndefined(instance?.isPlaying) ??
      booleanOrUndefined(player?.isPlaying) ??
      null,
  };
}

export function probePlayback(globals: CiderGlobals): PlaybackProbe {
  const player = playbackPlayer(globals);
  const instance = musicKit(globals);
  const audio = audioElement(globals, player);

  return {
    nowPlayingItem: player?.nowPlayingItem ?? instance?.nowPlayingItem ?? null,
    isPlaying:
      booleanOrUndefined(player?.isPlaying) ??
      booleanOrUndefined(instance?.isPlaying),
    currentPlaybackTime:
      numberOrUndefined(player?.currentPlaybackTime ?? player?.playbackTime) ??
      numberOrUndefined(instance?.currentPlaybackTime),
    currentPlaybackDuration:
      numberOrUndefined(player?.currentPlaybackDuration ?? player?.playbackDuration) ??
      numberOrUndefined(instance?.currentPlaybackDuration),
    audioCurrentTime: numberOrUndefined(audio?.currentTime),
    audioDuration: numberOrUndefined(audio?.duration),
  };
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
cd plugins/cider/lyrics
pnpm exec vitest run src/__tests__/playback.test.ts
```

Expected: all playback probe tests PASS.

- [ ] **Step 5: Commit the Cider fix**

```bash
git add plugins/cider/lyrics/src/__tests__/playback.test.ts plugins/cider/lyrics/src/probe/playback.ts plugins/cider/lyrics/src/probe/types.ts
git commit -m "fix(cider): restore current playback probing"
```

### Task 2: Reject Unusable MPRIS Durations

**Files:**
- Modify: `tests/test_mpris.py`
- Modify: `src/kotonoha/providers/mpris_track.py`

- [ ] **Step 1: Add failing duration validation tests**

Add these tests beside the existing sentinel test:

```python
def test_parse_non_finite_lengths_rejected():
    for value in (float("inf"), float("-inf"), float("nan")):
        assert parse_metadata({"mpris:length": value}).length_s is None


def test_parse_non_positive_lengths_rejected():
    assert parse_metadata({"mpris:length": 0}).length_s is None
    assert parse_metadata({"mpris:length": -1}).length_s is None


def test_parse_lengths_above_24_hours_rejected():
    assert parse_metadata({"mpris:length": 86_400_000_001}).length_s is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
uv run pytest tests/test_mpris.py -q
```

Expected: FAIL because non-finite, non-positive, and non-sentinel huge values currently convert to invalid seconds.

- [ ] **Step 3: Centralize credible-duration parsing**

In `src/kotonoha/providers/mpris_track.py`, import `math`, replace the exact-sentinel-only expression with a helper, and keep the public `TrackInfo` contract unchanged:

```python
import math

_MAX_TRACK_LENGTH_S = 24 * 60 * 60


def _length_seconds(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    length_us = float(value)
    if not math.isfinite(length_us):
        return None
    length_s = length_us / 1_000_000.0
    if length_s <= 0.0 or length_s > _MAX_TRACK_LENGTH_S:
        return None
    return length_s
```

Then use:

```python
length_s = _length_seconds(raw.get("mpris:length"))
```

The existing int64 sentinel test remains valid because the sentinel is far above 24 hours.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
uv run pytest tests/test_mpris.py -q
```

Expected: all MPRIS parser and stabilizer tests PASS.

- [ ] **Step 5: Commit the MPRIS fix**

```bash
git add tests/test_mpris.py src/kotonoha/providers/mpris_track.py
git commit -m "fix(mpris): reject unusable track lengths"
```

### Task 3: Verify Both Runtime Paths

**Files:**
- No production file changes expected

- [ ] **Step 1: Run the complete Cider plugin checks**

```bash
cd plugins/cider/lyrics
pnpm test
pnpm build
```

Expected: Vitest and the Vite/TypeScript build PASS.

- [ ] **Step 2: Run the complete Python checks**

```bash
uv run pytest
uv run ruff check .
uv run ty check
```

Expected: pytest, Ruff, and ty PASS.

- [ ] **Step 3: Verify the reloaded Cider plugin frames through CDP**

After Cider has loaded the newly built plugin, enable the CDP Network domain on the page target and inspect outgoing text frames for the Kotonoha payloads.

Expected:

```json
{"reason":"tick","currentTime":42.5,"isPlaying":true}
```

The exact time varies, but `currentTime` must be finite and advance while playing. The next full frame must contain a non-null `playback.nowPlayingItem`, a finite `playback.currentPlaybackTime`, and the current song metadata. Cider's unrelated `CU:Playback` Socket.IO frames are ignored.

- [ ] **Step 4: Inspect the resulting branch**

```bash
git status --short --branch
git log -4 --oneline --decorate
```

Expected: no uncommitted source or test changes; ignored Cider build output may exist without appearing in status. The latest commits describe the design, Cider fix, and MPRIS validation fix.
