import { describe, expect, it, vi } from "vitest";

import { ReconnectingLyricsSocket, frameSignature } from "../probe/transport";

const baseFrame = {
  lyrics: {
    found: true,
    songId: "song-1",
    currentLine: { id: "L1" },
    nextLine: { id: "L2" },
  },
  playback: { isPlaying: true },
} as any;

describe("frameSignature", () => {
  it("is stable for equivalent frames", () => {
    expect(frameSignature(baseFrame)).toBe(frameSignature({ ...baseFrame }));
  });

  it("changes when the current line changes", () => {
    const moved = { ...baseFrame, lyrics: { ...baseFrame.lyrics, currentLine: { id: "L2" } } };
    expect(frameSignature(moved)).not.toBe(frameSignature(baseFrame));
  });

  it("changes when play/pause toggles", () => {
    const paused = { ...baseFrame, playback: { isPlaying: false } };
    expect(frameSignature(paused)).not.toBe(frameSignature(baseFrame));
  });

  it("tolerates missing sections", () => {
    expect(frameSignature({ lyrics: undefined, playback: undefined } as any)).toBe("0||||0");
  });
});

// A minimal fake matching the slice of WebSocket the socket touches.
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 1; // OPEN
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closed = true;
  }
}

function makeSocket(overrides: Partial<ConstructorParameters<typeof ReconnectingLyricsSocket>[0]> = {}) {
  FakeWebSocket.instances = [];
  const timers: Array<{ handler: () => void; delay: number }> = [];
  const onOpen = vi.fn();
  const socket = new ReconnectingLyricsSocket({
    url: "ws://test/endpoint",
    onOpen,
    minBackoffMs: 500,
    maxBackoffMs: 5000,
    socketFactory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
    setTimeoutFn: (handler, delay) => {
      timers.push({ handler, delay });
      return timers.length - 1;
    },
    clearTimeoutFn: () => {},
    ...overrides,
  });
  return { socket, timers, onOpen, latest: () => FakeWebSocket.instances.at(-1)! };
}

describe("ReconnectingLyricsSocket", () => {
  it("calls onOpen and reports open after connect", () => {
    const { socket, onOpen, latest } = makeSocket();
    socket.connect();
    latest().onopen?.();
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(socket.isOpen).toBe(true);
  });

  it("queues a reconnect with exponential backoff on close", () => {
    const { socket, timers, latest } = makeSocket();
    socket.connect();
    latest().onopen?.();

    latest().onclose?.();
    expect(timers).toHaveLength(1);
    expect(timers[0].delay).toBe(500);

    // Fire the scheduled reconnect, then close again -> backoff doubles.
    timers[0].handler();
    latest().onclose?.();
    expect(timers[1].delay).toBe(1000);
  });

  it("resets backoff after a successful reopen", () => {
    const { socket, timers, latest } = makeSocket();
    socket.connect();
    latest().onclose?.();
    expect(timers[0].delay).toBe(500);
    timers[0].handler();
    latest().onclose?.();
    expect(timers[1].delay).toBe(1000);

    timers[1].handler();
    latest().onopen?.(); // success resets backoff
    latest().onclose?.();
    expect(timers[2].delay).toBe(500);
  });

  it("send returns false when not open and true when open", () => {
    const { socket, latest } = makeSocket();
    expect(socket.send("x")).toBe(false); // not connected yet
    socket.connect();
    latest().onopen?.();
    expect(socket.send("hello")).toBe(true);
    expect(latest().sent).toEqual(["hello"]);
  });

  it("routes server text messages to onMessage", () => {
    const onMessage = vi.fn();
    const { socket, latest } = makeSocket({ onMessage });
    socket.connect();
    latest().onmessage?.({ data: '{"type":"kotonoha/config"}' });
    latest().onmessage?.({ data: 123 }); // non-string ignored
    expect(onMessage).toHaveBeenCalledTimes(1);
    expect(onMessage).toHaveBeenCalledWith('{"type":"kotonoha/config"}');
  });

  it("stops reconnecting after close()", () => {
    const { socket, timers, latest } = makeSocket();
    socket.connect();
    const ws = latest();
    socket.close();
    ws.onclose?.();
    expect(timers).toHaveLength(0);
    expect(ws.closed).toBe(true);
  });
});
