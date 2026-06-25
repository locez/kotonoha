import type { ProbePayload } from "./types";

/** WebSocket.OPEN readyState value (spec-constant 1); avoids depending on a global WebSocket. */
const OPEN_READY_STATE = 1;

/**
 * A compact identity for a probe frame. Two frames with the same signature
 * describe the same lyric/playback situation, so we only need to push when the
 * signature changes (plus a periodic heartbeat for clock drift).
 *
 * Pure and side-effect free so it can be unit tested without a socket.
 */
export function frameSignature(payload: Pick<ProbePayload, "lyrics" | "playback">): string {
  const lyrics = payload.lyrics;
  const playing = payload.playback?.isPlaying ? "1" : "0";
  return [
    lyrics?.found ? "1" : "0",
    lyrics?.songId ?? "",
    lyrics?.currentLine?.id ?? "",
    lyrics?.nextLine?.id ?? "",
    playing,
  ].join("|");
}

export type ReconnectingSocketOptions = {
  url: string;
  /** Called every time a fresh connection opens (send a full snapshot here). */
  onOpen: () => void;
  /** Called with the text of each message Kotonoha sends back (e.g. config frames). */
  onMessage?: (data: string) => void;
  /** Optional logger for diagnostics. */
  log?: (message: string, error?: unknown) => void;
  /** Backoff bounds in milliseconds. */
  minBackoffMs?: number;
  maxBackoffMs?: number;
  /** Injectable for tests; defaults to the global WebSocket. */
  socketFactory?: (url: string) => WebSocket;
  /** Injectable timers for tests. */
  setTimeoutFn?: (handler: () => void, timeout: number) => number;
  clearTimeoutFn?: (handle: number) => void;
};

/**
 * Minimal WebSocket client that keeps trying to (re)connect with exponential
 * backoff. The Cider plugin uses it to stream lyric frames to Kotonoha; when
 * Kotonoha is not running yet, it simply retries quietly until it is.
 */
export class ReconnectingLyricsSocket {
  private ws: WebSocket | null = null;
  private backoff: number;
  private reconnectTimer: number | null = null;
  private closedByUser = false;

  private readonly url: string;
  private readonly onOpen: () => void;
  private readonly onMessage: (data: string) => void;
  private readonly log: (message: string, error?: unknown) => void;
  private readonly minBackoffMs: number;
  private readonly maxBackoffMs: number;
  private readonly socketFactory: (url: string) => WebSocket;
  private readonly setTimeoutFn: (handler: () => void, timeout: number) => number;
  private readonly clearTimeoutFn: (handle: number) => void;

  constructor(options: ReconnectingSocketOptions) {
    this.url = options.url;
    this.onOpen = options.onOpen;
    this.onMessage = options.onMessage ?? (() => {});
    this.log = options.log ?? (() => {});
    this.minBackoffMs = options.minBackoffMs ?? 500;
    this.maxBackoffMs = options.maxBackoffMs ?? 5000;
    this.socketFactory = options.socketFactory ?? ((url) => new WebSocket(url));
    this.setTimeoutFn = options.setTimeoutFn ?? ((h, t) => window.setTimeout(h, t));
    this.clearTimeoutFn = options.clearTimeoutFn ?? ((h) => window.clearTimeout(h));
    this.backoff = this.minBackoffMs;
  }

  get isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === OPEN_READY_STATE;
  }

  connect(): void {
    this.closedByUser = false;
    this.openSocket();
  }

  private openSocket(): void {
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    let socket: WebSocket;
    try {
      socket = this.socketFactory(this.url);
    } catch (error) {
      this.log("failed to construct socket", error);
      this.scheduleReconnect();
      return;
    }
    this.ws = socket;

    socket.onopen = () => {
      this.backoff = this.minBackoffMs;
      this.log("connected");
      this.onOpen();
    };
    socket.onmessage = (event: MessageEvent) => {
      if (typeof event.data === "string") {
        this.onMessage(event.data);
      }
    };
    socket.onclose = () => {
      this.log("disconnected");
      this.scheduleReconnect();
    };
    socket.onerror = (event) => {
      this.log("socket error", event);
      // onclose follows onerror; reconnect is scheduled there.
    };
  }

  private scheduleReconnect(): void {
    this.ws = null;
    if (this.closedByUser || this.reconnectTimer !== null) {
      return;
    }
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, this.maxBackoffMs);
    this.reconnectTimer = this.setTimeoutFn(() => {
      this.reconnectTimer = null;
      this.openSocket();
    }, delay);
  }

  /** Send a text frame if connected; returns whether it was sent. */
  send(data: string): boolean {
    if (!this.isOpen || this.ws === null) {
      return false;
    }
    try {
      this.ws.send(data);
      return true;
    } catch (error) {
      this.log("send failed", error);
      return false;
    }
  }

  close(): void {
    this.closedByUser = true;
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws !== null) {
      try {
        this.ws.close();
      } catch {
        // ignore
      }
      this.ws = null;
    }
  }
}
