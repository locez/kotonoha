const DEVELOPMENT_VERSION = "0.0.1";

export function resolvePluginVersion(value: string | undefined): string {
  if (value === undefined || value === "") {
    return DEVELOPMENT_VERSION;
  }

  if (!/^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/.test(value)) {
    throw new Error(`Invalid KOTONOHA_VERSION "${value}": expected X.Y.Z`);
  }

  return value;
}

export default {
  ce_prefix: "kotonoha-cider-lyrics",
  identifier: "dev.locez.kotonoha.cider.lyrics",
  name: "Kotonoha Cider Lyrics",
  description: "Probes Cider's Apple Music TTML lyrics for a Linux lyrics overlay bridge.",
  version: resolvePluginVersion(process.env.KOTONOHA_VERSION),
  author: "Locez",
  repo: "https://github.com/locez/kotonoha",
  pluginKitVersion: "4",
  entry: {
    "plugin.js": {
      type: "main",
    },
  },
};
