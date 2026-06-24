import type { PlaybackProbe } from "./types";

type CiderGlobals = {
  CiderApp?: any;
  __PLUGINSYS__?: any;
};

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
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
