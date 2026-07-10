import { describe, expect, it } from "vitest";

import { resolvePluginVersion } from "../plugin.config";

describe("resolvePluginVersion", () => {
  it("uses the development version when the build version is missing", () => {
    expect(resolvePluginVersion(undefined)).toBe("0.0.1");
    expect(resolvePluginVersion("")).toBe("0.0.1");
  });

  it.each(["0.0.0", "0.1.0", "10.20.30"])("accepts canonical release version %s", (version) => {
    expect(resolvePluginVersion(version)).toBe(version);
  });

  it.each(["v1.2.3", "1.2", "1.2.3.4", "one.two.three", "01.2.3", "1.02.3", "1.2.03"])(
    "rejects invalid version %s",
    (version) => {
      expect(() => resolvePluginVersion(version)).toThrow(/X\.Y\.Z/);
    },
  );
});
