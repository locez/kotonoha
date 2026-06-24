import { describe, expect, it } from "vitest";

import { probePlayback } from "../probe/playback";

describe("probePlayback", () => {
  it("reads the PluginKit apple music store when present", () => {
    const globals = {
      __PLUGINSYS__: {
        Stores: {
          appleMusicStore: {
            nowPlayingItem: { title: "Song" },
            isPlaying: true,
            currentPlaybackTime: 42,
            audioElement: {
              currentTime: 42.5,
              duration: 180,
            },
          },
        },
      },
    };

    expect(probePlayback(globals)).toEqual({
      nowPlayingItem: { title: "Song" },
      isPlaying: true,
      currentPlaybackTime: 42,
      audioCurrentTime: 42.5,
      audioDuration: 180,
    });
  });

  it("falls back to CiderApp musicKitStore", () => {
    const globals = {
      CiderApp: {
        musicKitStore: {
          nowPlayingItem: { title: "Fallback" },
          playbackTime: 8,
        },
      },
    };

    expect(probePlayback(globals)).toMatchObject({
      nowPlayingItem: { title: "Fallback" },
      currentPlaybackTime: 8,
    });
  });
});
