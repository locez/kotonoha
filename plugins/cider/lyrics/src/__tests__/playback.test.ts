import { describe, expect, it } from "vitest";

import { probePlayback, probePlaybackTime } from "../probe/playback";

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

  it("reads the current Cider nested player layout", () => {
    const nowPlayingItem = { attributes: { name: "Current Song" } };
    const globals = {
      CiderApp: {
        musicKitStore: {
          player: {
            nowPlayingItem,
            isPlaying: true,
            currentPlaybackTime: 41,
            currentPlaybackDuration: 180,
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          nowPlayingItem,
          isPlaying: true,
          currentPlaybackTime: 42.5,
          currentPlaybackDuration: 180,
        }),
      },
    };

    expect(probePlayback(globals)).toMatchObject({
      nowPlayingItem,
      isPlaying: true,
      currentPlaybackTime: 41,
      currentPlaybackDuration: 180,
    });
  });

  it("uses MusicKit for a high-frequency tick when Cider exposes no audio element", () => {
    const globals = {
      CiderApp: {
        musicKitStore: {
          player: {
            isPlaying: true,
            currentPlaybackTime: 41,
          },
        },
      },
      MusicKit: {
        getInstance: () => ({
          isPlaying: true,
          currentPlaybackTime: 42.5,
        }),
      },
    };

    expect(probePlaybackTime(globals)).toEqual({
      currentTime: 42.5,
      isPlaying: true,
    });
  });
});
