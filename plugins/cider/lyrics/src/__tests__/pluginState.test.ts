import { describe, expect, it } from "vitest";

import { dedupeAppliedPluginList } from "../probe/pluginState";

describe("dedupeAppliedPluginList", () => {
  it("deduplicates Cider's applied plugin list while preserving order", () => {
    const storage = new Map<string, string>();
    storage.set(
      "c3api/applied-plugins",
      JSON.stringify(["other.plugin", "dev.locez.kotonoha.cider.lyrics", "dev.locez.kotonoha.cider.lyrics"]),
    );

    const result = dedupeAppliedPluginList(storage, "dev.locez.kotonoha.cider.lyrics");

    expect(result).toEqual({
      changed: true,
      before: 3,
      after: 2,
    });
    expect(JSON.parse(storage.get("c3api/applied-plugins") ?? "[]")).toEqual([
      "other.plugin",
      "dev.locez.kotonoha.cider.lyrics",
    ]);
  });

  it("ignores missing or invalid applied plugin lists", () => {
    const storage = new Map<string, string>();
    storage.set("c3api/applied-plugins", "not json");

    expect(dedupeAppliedPluginList(storage, "dev.locez.kotonoha.cider.lyrics")).toEqual({
      changed: false,
      before: 0,
      after: 0,
    });
    expect(storage.get("c3api/applied-plugins")).toBe("not json");
  });
});
