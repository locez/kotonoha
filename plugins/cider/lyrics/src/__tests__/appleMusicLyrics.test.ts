import { describe, expect, it, vi } from "vitest";

import { probeAppleMusicLyrics } from "../probe/appleMusicLyrics";

const TTML = `
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:itunes="http://music.apple.com/lyric-ttml-internal"
    xml:lang="en"
    itunes:timing="Line">
  <body>
    <div>
      <p xml:id="L1" begin="00:01.000" end="00:03.000">hello</p>
      <p xml:id="L2" begin="00:03.000" end="00:05.000">world</p>
    </div>
  </body>
</tt>`;

describe("probeAppleMusicLyrics", () => {
  it("fetches and parses current Apple Music lyrics without using DOM", async () => {
    const mkfetch = vi.fn().mockResolvedValue({
      data: {
        data: [
          {
            attributes: {
              ttml: TTML,
            },
          },
        ],
      },
    });

    const result = await probeAppleMusicLyrics({
      CiderApp: {
        mkfetch,
        musicKitStore: {
          player: {
            nowPlayingId: "song-1",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 3.5,
          nowPlayingItem: {
            id: "song-1",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    });

    expect(mkfetch).toHaveBeenCalledWith("/v1/catalog/$MUSIC_STOREFRONT/songs/song-1/syllable-lyrics");
    expect(result).toMatchObject({
      found: true,
      provider: "Apple Music",
      songId: "song-1",
      timing: "Line",
      language: "en",
      lineCount: 2,
      currentTime: 3.5,
      currentLine: {
        id: "L2",
        text: "world",
      },
      previousLine: {
        id: "L1",
      },
      nextLine: null,
      aroundLines: [
        {
          id: "L1",
          text: "hello",
        },
        {
          id: "L2",
          text: "world",
        },
      ],
    });
    expect("lines" in result).toBe(false);
  });

  it("keeps a current song working set without emitting full lyrics", async () => {
    const mkfetch = vi.fn().mockResolvedValue({
      data: {
        data: [
          {
            attributes: {
              ttml: TTML,
            },
          },
        ],
      },
    });
    const globals = {
      CiderApp: {
        mkfetch,
        musicKitStore: {
          player: {
            nowPlayingId: "song-3",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 3.5,
          nowPlayingItem: {
            id: "song-3",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    };

    await probeAppleMusicLyrics(globals);
    const result = await probeAppleMusicLyrics(globals);

    expect(mkfetch).toHaveBeenCalledTimes(1);
    expect("lines" in result).toBe(false);
    expect(result.currentLine?.text).toBe("world");
    expect(result.aroundLines.map((line) => line.text)).toEqual(["hello", "world"]);
  });

  it("returns a structured miss when lyrics are unavailable", async () => {
    const result = await probeAppleMusicLyrics({
      CiderApp: {
        mkfetch: vi.fn().mockResolvedValue({ data: { data: [{}] } }),
        musicKitStore: {
          player: {
            nowPlayingId: "song-2",
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          currentPlaybackTime: 0,
          nowPlayingItem: {
            id: "song-2",
            attributes: {
              durationInMillis: 6000,
            },
          },
        }),
      },
    });

    expect(result).toMatchObject({
      found: false,
      provider: "Apple Music",
      songId: "song-2",
      lineCount: 0,
      aroundLines: [],
      error: "No Apple Music TTML returned",
    });
    expect("lines" in result).toBe(false);
  });
});
