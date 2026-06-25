import { findCurrentLine, parseAppleMusicTtml } from "./ttml";
import type { LyricsProbe, TimedLyricLine } from "./types";

const AROUND_WINDOW_SECONDS = 8;

type CiderGlobals = {
  CiderApp?: any;
  MusicKit?: any;
};

type LyricsCacheEntry = {
  songId: string;
  timing: string | null;
  language: string | null;
  lines: TimedLyricLine[];
};

let currentLyrics: LyricsCacheEntry | null = null;

// Which translation language to extract from the TTML. Kotonoha pushes this
// over the WebSocket (derived from the system locale or the user's setting);
// changing it invalidates the cache so the next probe re-parses.
let preferredTranslationLanguage = "zh-Hans";

export function setPreferredTranslationLanguage(language: string): void {
  if (!language || language === preferredTranslationLanguage) {
    return;
  }
  preferredTranslationLanguage = language;
  currentLyrics = null; // force re-parse with the new language
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function currentPlaybackTime(globals: CiderGlobals): number | null {
  return numberOrNull(globals.MusicKit?.getInstance?.()?.currentPlaybackTime);
}

function currentNowPlayingItem(globals: CiderGlobals): any {
  return globals.MusicKit?.getInstance?.()?.nowPlayingItem ?? null;
}

function currentSongId(globals: CiderGlobals): string | null {
  return (
    globals.CiderApp?.musicKitStore?.player?.nowPlayingId ??
    globals.CiderApp?.musicKitStore?.player?.nowPlayingItem?._songId ??
    globals.CiderApp?.musicKitStore?.player?.nowPlayingItem?.id ??
    currentNowPlayingItem(globals)?._songId ??
    currentNowPlayingItem(globals)?.id ??
    null
  );
}

function currentDurationSeconds(globals: CiderGlobals): number | null {
  const item = currentNowPlayingItem(globals);
  return numberOrNull(item?.attributes?.durationInMillis)
    ? item.attributes.durationInMillis / 1000
    : null;
}

function emptyLyricsProbe(songId: string | null, currentTime: number | null, error?: string): LyricsProbe {
  return {
    found: false,
    provider: "Apple Music",
    songId,
    timing: null,
    language: null,
    lineCount: 0,
    currentTime,
    currentLine: null,
    previousLine: null,
    nextLine: null,
    aroundLines: [],
    ...(error ? { error } : {}),
  };
}

function withCurrentLine(entry: LyricsCacheEntry, currentTime: number | null): LyricsProbe {
  const currentLine = findCurrentLine(entry.lines, currentTime);
  const currentIndex = currentLine?.index ?? -1;
  const aroundLines =
    currentTime === null
      ? []
      : entry.lines.filter((line) => (
          line.start <= currentTime + AROUND_WINDOW_SECONDS &&
          line.end >= currentTime - AROUND_WINDOW_SECONDS
        ));

  return {
    found: entry.lines.length > 0,
    provider: "Apple Music",
    songId: entry.songId,
    timing: entry.timing,
    language: entry.language,
    lineCount: entry.lines.length,
    currentTime,
    currentLine,
    previousLine: currentIndex > 0 ? entry.lines[currentIndex - 1] : null,
    nextLine: currentIndex >= 0 ? entry.lines[currentIndex + 1] ?? null : null,
    aroundLines,
  };
}

async function fetchLyrics(globals: CiderGlobals, songId: string): Promise<LyricsCacheEntry> {
  const response = await globals.CiderApp?.mkfetch?.(
    `/v1/catalog/$MUSIC_STOREFRONT/songs/${songId}/syllable-lyrics`,
  );
  const ttml = response?.data?.data?.[0]?.attributes?.ttml;
  if (typeof ttml !== "string" || ttml.trim().length === 0) {
    throw new Error("No Apple Music TTML returned");
  }

  const parsed = parseAppleMusicTtml(ttml, {
    durationSeconds: currentDurationSeconds(globals),
    preferredTranslationLanguage,
  });

  return {
    songId,
    timing: parsed.timing,
    language: parsed.language,
    lines: parsed.lines,
  };
}

export async function probeAppleMusicLyrics(globals: CiderGlobals): Promise<LyricsProbe> {
  const songId = currentSongId(globals);
  const playbackTime = currentPlaybackTime(globals);

  if (!songId) {
    return emptyLyricsProbe(null, playbackTime, "No current song id");
  }

  if (currentLyrics?.songId === songId) {
    return withCurrentLine(currentLyrics, playbackTime);
  }

  try {
    currentLyrics = await fetchLyrics(globals, songId);
    return withCurrentLine(currentLyrics, playbackTime);
  } catch (error) {
    currentLyrics = null;
    return emptyLyricsProbe(songId, playbackTime, error instanceof Error ? error.message : String(error));
  }
}
