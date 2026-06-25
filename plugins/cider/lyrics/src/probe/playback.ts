import type { PlaybackProbe } from "./types";

type CiderGlobals = {
  CiderApp?: any;
  __PLUGINSYS__?: any;
};

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

/**
 * Lightweight, high-frequency read of just the playback head + play state.
 *
 * Prefers the underlying HTMLMediaElement (`audio.currentTime` / `audio.paused`)
 * because those are native, high-precision and reliable — unlike the store's
 * `isPlaying` flag, which has proven unreliable. Used by the ~100ms tick loop so
 * Kotonoha's local clock is frequently re-calibrated against ground truth.
 */
export function probePlaybackTime(globals: any): { currentTime: number | null; isPlaying: boolean | null } {
  const store =
    globals.__PLUGINSYS__?.Stores?.appleMusicStore ??
    globals.CiderApp?.musicKitStore ??
    globals.CiderApp?.store;
  const audio = store?.audioElement ?? globals.CiderApp?.musicKitStore?.audioElement;

  if (audio) {
    return {
      currentTime: numberOrUndefined(audio.currentTime) ?? null,
      isPlaying: typeof audio.paused === "boolean" ? !audio.paused : null,
    };
  }
  return {
    currentTime: numberOrUndefined(store?.currentPlaybackTime ?? store?.playbackTime) ?? null,
    isPlaying: typeof store?.isPlaying === "boolean" ? store.isPlaying : null,
  };
}

export function probePlayback(globals: CiderGlobals): PlaybackProbe {
  const store =
    globals.__PLUGINSYS__?.Stores?.appleMusicStore ??
    globals.CiderApp?.musicKitStore ??
    globals.CiderApp?.store;

  const audio = store?.audioElement ?? globals.CiderApp?.musicKitStore?.audioElement;

  return {
    nowPlayingItem: store?.nowPlayingItem ?? globals.CiderApp?.musicKitStore?.nowPlayingItem ?? null,
    isPlaying: typeof store?.isPlaying === "boolean" ? store.isPlaying : undefined,
    currentPlaybackTime: numberOrUndefined(store?.currentPlaybackTime ?? store?.playbackTime),
    audioCurrentTime: numberOrUndefined(audio?.currentTime),
    audioDuration: numberOrUndefined(audio?.duration),
  };
}
