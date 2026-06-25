import {
  addMainMenuEntry,
  definePluginContext,
} from "@ciderapp/pluginkit";

import { setPreferredTranslationLanguage } from "./probe/appleMusicLyrics";
import { createProbePayload } from "./probe/payload";
import { probePlaybackTime } from "./probe/playback";
import { dedupeBrowserAppliedPluginList } from "./probe/pluginState";
import { ReconnectingLyricsSocket, frameSignature } from "./probe/transport";
import type { FrameReason, ProbeConfig } from "./probe/types";
import PluginConfig from "./plugin.config";

const DEFAULT_CONFIG: ProbeConfig = {
  endpoint: "ws://127.0.0.1:28745/kotonoha/cider/lyrics",
  pollMs: 200,
  heartbeatMs: 1000,
  tickMs: 100,
  consoleLog: false,
};

let pollId: number | undefined;
let tickId: number | undefined;
let socket: ReconnectingLyricsSocket | undefined;

// Change-detection / heartbeat bookkeeping.
let lastSignature: string | null = null;
let lastSentAt = 0;
let building = false;

const { plugin, setupConfig, customElementName, goToPage, useCPlugin } =
  definePluginContext({
    ...PluginConfig,
    setup() {
      dedupeBrowserAppliedPluginList(PluginConfig.identifier);

      addMainMenuEntry({
        label: "Lyrics Probe: send snapshot",
        onClick() {
          void pushFrame("manual");
        },
      });

      startSocket();
      startProbeLoop();
      startTickLoop();
    },
  });

export const cfg = setupConfig(DEFAULT_CONFIG);

function currentConfig(): ProbeConfig {
  return {
    ...DEFAULT_CONFIG,
    ...(cfg.value ?? {}),
  };
}

function log(message: string, error?: unknown) {
  if (currentConfig().consoleLog) {
    if (error !== undefined) {
      console.warn("[kotonoha-cider-lyrics]", message, error);
    } else {
      console.log("[kotonoha-cider-lyrics]", message);
    }
  }
}

function startSocket() {
  socket?.close();
  socket = new ReconnectingLyricsSocket({
    url: currentConfig().endpoint,
    log,
    // On every (re)connect, push a full snapshot immediately so the overlay is
    // never blank waiting for the next change.
    onOpen() {
      lastSignature = null;
      void pushFrame("open");
    },
    // Kotonoha sends back its preferred translation language (system locale or
    // the user's setting); apply it so the next probe extracts that language.
    onMessage: handleServerMessage,
  });
  socket.connect();
}

function handleServerMessage(data: string) {
  try {
    const message = JSON.parse(data);
    if (message?.type === "kotonoha/config" && typeof message.translationLanguage === "string") {
      setPreferredTranslationLanguage(message.translationLanguage);
      log(`translation language set to ${message.translationLanguage}`);
    }
  } catch (error) {
    log("failed to handle server message", error);
  }
}

function startProbeLoop() {
  if (pollId !== undefined) {
    window.clearInterval(pollId);
  }
  const config = currentConfig();
  pollId = window.setInterval(() => {
    void tick();
  }, Math.max(50, config.pollMs));
}

// Lightweight high-frequency clock calibration: just the real playback head +
// paused state, no lyric work. Kotonoha interpolates between these at 60fps, so
// the sweep stays both accurate (frequently re-calibrated) and smooth.
function startTickLoop() {
  if (tickId !== undefined) {
    window.clearInterval(tickId);
  }
  const config = currentConfig();
  tickId = window.setInterval(() => {
    if (socket === undefined || !socket.isOpen) {
      return;
    }
    const { currentTime, isPlaying } = probePlaybackTime(window);
    if (currentTime === null) {
      return;
    }
    socket.send(JSON.stringify({ reason: "tick", currentTime, isPlaying }));
  }, Math.max(30, config.tickMs));
}

/** Sample Cider state; send only when the situation changed or a heartbeat is due. */
async function tick() {
  if (building || socket === undefined || !socket.isOpen) {
    return;
  }
  building = true;
  try {
    const config = currentConfig();
    const payload = await createProbePayload({
      globals: window,
      version: PluginConfig.version,
    });
    const signature = frameSignature(payload);
    const now = Date.now();

    const changed = signature !== lastSignature;
    const heartbeatDue = now - lastSentAt >= config.heartbeatMs;
    if (!changed && !heartbeatDue) {
      return;
    }
    sendBuiltPayload(payload, changed ? "change" : "heartbeat", signature, now);
  } catch (error) {
    log("probe tick failed", error);
  } finally {
    building = false;
  }
}

/** Build + send a frame unconditionally (used for open/manual). */
async function pushFrame(reason: FrameReason) {
  if (socket === undefined) {
    return;
  }
  try {
    const payload = await createProbePayload({
      globals: window,
      version: PluginConfig.version,
    });
    sendBuiltPayload(payload, reason, frameSignature(payload), Date.now());
  } catch (error) {
    log("pushFrame failed", error);
  }
}

function sendBuiltPayload(
  payload: Awaited<ReturnType<typeof createProbePayload>>,
  reason: FrameReason,
  signature: string,
  now: number,
) {
  const frame = { ...payload, reason };
  log(`send ${reason}`);
  const sent = socket?.send(JSON.stringify(frame)) ?? false;
  if (sent) {
    lastSignature = signature;
    lastSentAt = now;
  }
}

export { setupConfig, customElementName, goToPage, useCPlugin };

export default plugin;
