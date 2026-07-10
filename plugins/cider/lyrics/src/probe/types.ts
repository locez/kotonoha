export type ProbeConfig = {
  /** Kotonoha WebSocket endpoint, e.g. ws://127.0.0.1:28745/kotonoha/cider/lyrics */
  endpoint: string;
  /** How often to sample Cider state for change detection. */
  pollMs: number;
  /** Floor interval for heartbeat frames (clock-drift correction) when nothing changes. */
  heartbeatMs: number;
  /** Interval for lightweight tick frames (currentTime + paused) that calibrate the clock. */
  tickMs: number;
  consoleLog: boolean;
};

export type FrameReason = "open" | "change" | "heartbeat" | "manual";

export type TimedLyricWord = {
  start: number | null;
  end: number | null;
  text: string;
};

export type TimedLyricLine = {
  index: number;
  id: string;
  start: number;
  end: number;
  text: string;
  translation: string;
  words: TimedLyricWord[];
};

export type LyricsProbe = {
  found: boolean;
  provider: "Apple Music";
  songId: string | null;
  timing: string | null;
  language: string | null;
  lineCount: number;
  currentTime: number | null;
  currentLine: TimedLyricLine | null;
  previousLine: TimedLyricLine | null;
  nextLine: TimedLyricLine | null;
  aroundLines: TimedLyricLine[];
  error?: string;
};

export type PlaybackProbe = {
  nowPlayingItem: unknown;
  isPlaying?: boolean;
  currentPlaybackTime?: number;
  currentPlaybackDuration?: number;
  audioCurrentTime?: number;
  audioDuration?: number;
};

export type ProbePayload = {
  source: "kotonoha-cider-lyrics";
  version: string;
  capturedAt: string;
  locationHref: string;
  playback: PlaybackProbe;
  lyrics: LyricsProbe;
};
