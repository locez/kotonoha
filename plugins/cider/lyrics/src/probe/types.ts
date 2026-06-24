export type ProbeConfig = {
  endpoint: string;
  intervalMs: number;
  consoleLog: boolean;
};

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
