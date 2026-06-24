import { describe, expect, it, vi } from "vitest";

import { createProbePayload } from "../probe/payload";

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

describe("createProbePayload", () => {
  it("emits current lyric context, not full static lyrics", async () => {
    const payload = await createProbePayload({
      version: "0.0.1",
      globals: {
        location: {
          href: "http://127.0.0.1:10767/index.html#/am/home",
        },
        CiderApp: {
          mkfetch: vi.fn().mockResolvedValue({
            data: {
              data: [
                {
                  attributes: {
                    ttml: TTML,
                  },
                },
              ],
            },
          }),
          musicKitStore: {
            player: {
              nowPlayingId: "song-payload",
            },
          },
        },
        MusicKit: {
          getInstance: () => ({
            currentPlaybackTime: 3.5,
            nowPlayingItem: {
              id: "song-payload",
              attributes: {
                durationInMillis: 6000,
              },
            },
          }),
        },
      },
    });

    expect(payload.lyrics).toMatchObject({
      found: true,
      songId: "song-payload",
      lineCount: 2,
      currentLine: {
        text: "world",
      },
      aroundLines: [
        { text: "hello" },
        { text: "world" },
      ],
    });
    expect("lines" in payload.lyrics).toBe(false);
  });
});
