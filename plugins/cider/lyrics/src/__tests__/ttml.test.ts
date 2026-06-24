import { describe, expect, it } from "vitest";

import { findCurrentLine, parseAppleMusicTtml } from "../probe/ttml";

const LINE_TTML = `<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml"
    xmlns:itunes="http://music.apple.com/lyric-ttml-internal"
    xmlns:ttm="http://www.w3.org/ns/ttml#metadata"
    itunes:timing="Line"
    xml:lang="zh-Hant">
  <head>
    <metadata>
      <iTunesMetadata xmlns="http://music.apple.com/lyric-ttml-internal">
        <translations>
          <translation xml:lang="zh-Hans">
            <text for="L1">第一行简体</text>
            <text for="L2">第二行简体</text>
          </translation>
        </translations>
      </iTunesMetadata>
    </metadata>
  </head>
  <body>
    <div>
      <p xml:id="L1" begin="00:01.000" end="00:03.000">第一行繁體</p>
      <p xml:id="L2" begin="00:03.500" end="01:00:01.000">第二行繁體</p>
      <p xml:id="L3" begin="00:06.000" end="00:07.000">第三行繁體</p>
    </div>
  </body>
</tt>`;

describe("parseAppleMusicTtml", () => {
  it("parses line-synced Apple Music TTML and translations", () => {
    const result = parseAppleMusicTtml(LINE_TTML, { durationSeconds: 10 });

    expect(result.timing).toBe("Line");
    expect(result.language).toBe("zh-Hant");
    expect(result.lines).toEqual([
      {
        index: 0,
        id: "L1",
        start: 1,
        end: 3,
        text: "第一行繁體",
        translation: "第一行简体",
        words: [],
      },
      {
        index: 1,
        id: "L2",
        start: 3.5,
        end: 6,
        text: "第二行繁體",
        translation: "第二行简体",
        words: [],
      },
      {
        index: 2,
        id: "L3",
        start: 6,
        end: 7,
        text: "第三行繁體",
        translation: "",
        words: [],
      },
    ]);
  });

  it("finds the current line by playback time", () => {
    const parsed = parseAppleMusicTtml(LINE_TTML, { durationSeconds: 10 });

    expect(findCurrentLine(parsed.lines, 4)?.id).toBe("L2");
    expect(findCurrentLine(parsed.lines, 9)).toBeNull();
  });
});
