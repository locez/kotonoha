import type { PlaybackProbe } from "./types";

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
    ),
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

/**
 * Lightweight, high-frequency read of just the playback head + play state.
 *
 * Prefers an explicitly exposed HTMLMediaElement, then MusicKit's continuous
 * song clock, then the resolved Cider player store. Used by the ~100ms tick loop
 * so Kotonoha's local clock is frequently re-calibrated against ground truth.
 */
export function probePlaybackTime(globals: any): {
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
