import { probeAppleMusicLyrics } from "./appleMusicLyrics";
import { probePlayback } from "./playback";
import type { ProbePayload } from "./types";

export async function createProbePayload(options: {
  globals: any;
  version: string;
}): Promise<ProbePayload> {
  return {
    source: "kotonoha-cider-lyrics",
    version: options.version,
    capturedAt: new Date().toISOString(),
    locationHref: options.globals.location?.href ?? "",
    playback: probePlayback(options.globals),
    lyrics: await probeAppleMusicLyrics(options.globals),
  };
}
