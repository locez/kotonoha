import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import { defineConfig } from "vitest/config";
import type { Plugin } from "vite";
import cssInjectedByJsPlugin from "vite-plugin-css-injected-by-js";
import { stringify } from "yaml";

import pluginConfig from "./src/plugin.config";

const kotonohaVersion = process.env.KOTONOHA_VERSION ?? "";

function ciderPluginManifest(): Plugin {
  return {
    name: "cider-plugin-manifest",
    apply: "build" as const,
    buildStart() {
      this.emitFile({
        fileName: "plugin.yml",
        type: "asset",
        source: stringify(pluginConfig),
      });
    },
  };
}

export default defineConfig({
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
    "process.env": JSON.stringify({
      NODE_ENV: "production",
      cider: "2",
      KOTONOHA_VERSION: kotonohaVersion,
    }),
    cplugin: JSON.stringify({
      ce_prefix: pluginConfig.ce_prefix,
      identifier: pluginConfig.identifier,
    }),
  },
  plugins: [
    vue({
      template: {
        compilerOptions: {
          isCustomElement: (tag) => tag.startsWith("cider-"),
        },
      },
    }),
    AutoImport({
      imports: ["vue"],
      dts: true,
    }),
    cssInjectedByJsPlugin(),
    ciderPluginManifest(),
  ],
  resolve: {
    tsconfigPaths: true,
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    emptyOutDir: true,
    outDir: "dist/dev.locez.kotonoha.cider.lyrics",
    lib: {
      entry: "src/main.ts",
      name: "CiderLyricsProbe",
      formats: ["es"],
      fileName: () => "plugin.js",
    },
  },
  test: {
    environment: "jsdom",
  },
});
