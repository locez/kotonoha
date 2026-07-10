import { describe, expect, it } from "vitest";

import { resolvePluginVersion } from "../plugin.config";

describe("resolvePluginVersion", () => {
  it("uses the development version when the build version is missing", () => {
    expect(resolvePluginVersion(undefined)).toBe("0.0.1");
    expect(resolvePluginVersion("")).toBe("0.0.1");
  });

  it("accepts an exact release version", () => {
    expect(resolvePluginVersion("1.2.3")).toBe("1.2.3");
  });

  it.each(["v1.2.3", "1.2", "1.2.3.4", "one.two.three"])("rejects invalid version %s", (version) => {
    expect(() => resolvePluginVersion(version)).toThrow(/X\.Y\.Z/);
  });
});
