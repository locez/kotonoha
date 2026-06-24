import {
  addMainMenuEntry,
  definePluginContext,
} from "@ciderapp/pluginkit";

import { createProbePayload } from "./probe/payload";
import { dedupeBrowserAppliedPluginList } from "./probe/pluginState";
import type { ProbeConfig } from "./probe/types";
import PluginConfig from "./plugin.config";

const DEFAULT_CONFIG: ProbeConfig = {
  endpoint: "http://127.0.0.1:28745/kotonoha/cider/lyrics",
  intervalMs: 1000,
  consoleLog: false,
};

let intervalId: number | undefined;

const { plugin, setupConfig, customElementName, goToPage, useCPlugin } =
  definePluginContext({
    ...PluginConfig,
    setup() {
      dedupeBrowserAppliedPluginList(PluginConfig.identifier);

      addMainMenuEntry({
        label: "Lyrics Probe: send snapshot",
        onClick() {
          void sendProbeSnapshot("manual");
        },
      });

      startProbeLoop();
      void sendProbeSnapshot("startup");
    },
  });

export const cfg = setupConfig(DEFAULT_CONFIG);

function currentConfig(): ProbeConfig {
  return {
    ...DEFAULT_CONFIG,
    ...(cfg.value ?? {}),
    consoleLog: false,
  };
}

function startProbeLoop() {
  if (intervalId !== undefined) {
    window.clearInterval(intervalId);
  }

  const config = currentConfig();
  intervalId = window.setInterval(() => {
    void sendProbeSnapshot("interval");
  }, Math.max(250, config.intervalMs));
}

async function sendProbeSnapshot(reason: "startup" | "interval" | "manual") {
  const config = currentConfig();

  const payload = {
    ...(await createProbePayload({
      globals: window,
      version: PluginConfig.version,
    })),
    reason,
  };

  if (config.consoleLog) {
    console.log("[kotonoha-cider-lyrics]", payload);
  }

  try {
    await fetch(config.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    if (config.consoleLog) {
      console.warn("[kotonoha-cider-lyrics] failed to post payload", error);
    }
  }
}

export { setupConfig, customElementName, goToPage, useCPlugin };

export default plugin;
