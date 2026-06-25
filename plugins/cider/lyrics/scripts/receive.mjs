// Standalone debug receiver for the Cider lyrics probe.
//
// The probe now speaks WebSocket (see src/probe/transport.ts), so this is a
// minimal zero-dependency WS server that prints each lyric frame. It mirrors
// what Kotonoha's Python receiver does, for use when Kotonoha is not running.
//
//   node scripts/receive.mjs
//
// Note: this only decodes the masked, unfragmented text frames the probe sends.

import { createHash } from "node:crypto";
import { createServer } from "node:http";

const host = "127.0.0.1";
const port = Number.parseInt(process.env.CIDER_LYRICS_PROBE_PORT ?? "28745", 10);
const path = "/kotonoha/cider/lyrics";
const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

const server = createServer((req, res) => {
  res.writeHead(426, { "Content-Type": "text/plain; charset=utf-8" });
  res.end("Upgrade required: this endpoint speaks WebSocket.\n");
});

server.on("upgrade", (req, socket) => {
  if (req.url !== path) {
    socket.write("HTTP/1.1 404 Not Found\r\n\r\n");
    socket.destroy();
    return;
  }
  const key = req.headers["sec-websocket-key"];
  if (typeof key !== "string") {
    socket.destroy();
    return;
  }
  const accept = createHash("sha1").update(key + WS_GUID).digest("base64");
  socket.write(
    "HTTP/1.1 101 Switching Protocols\r\n" +
      "Upgrade: websocket\r\n" +
      "Connection: Upgrade\r\n" +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  console.log(`[${new Date().toISOString()}] probe connected`);

  let buffer = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    buffer = Buffer.concat([buffer, chunk]);
    buffer = drainFrames(buffer, socket);
  });
  socket.on("close", () => console.log(`[${new Date().toISOString()}] probe disconnected`));
  socket.on("error", () => socket.destroy());
});

/** Decode as many complete frames as `buffer` holds; return the unconsumed tail. */
function drainFrames(buffer, socket) {
  while (buffer.length >= 2) {
    const fin = (buffer[0] & 0x80) !== 0;
    const opcode = buffer[0] & 0x0f;
    const masked = (buffer[1] & 0x80) !== 0;
    let len = buffer[1] & 0x7f;
    let offset = 2;

    if (len === 126) {
      if (buffer.length < offset + 2) break;
      len = buffer.readUInt16BE(offset);
      offset += 2;
    } else if (len === 127) {
      if (buffer.length < offset + 8) break;
      len = Number(buffer.readBigUInt64BE(offset));
      offset += 8;
    }

    const maskLen = masked ? 4 : 0;
    if (buffer.length < offset + maskLen + len) break; // wait for more bytes

    const maskKey = masked ? buffer.subarray(offset, offset + 4) : null;
    offset += maskLen;
    const payload = Buffer.from(buffer.subarray(offset, offset + len));
    if (maskKey) {
      for (let i = 0; i < payload.length; i++) payload[i] ^= maskKey[i % 4];
    }
    buffer = buffer.subarray(offset + len);

    if (opcode === 0x8) {
      socket.end(); // close
      break;
    } else if (opcode === 0x9) {
      socket.write(buildFrame(0xa, payload)); // ping -> pong
    } else if (opcode === 0x1 && fin) {
      handleText(payload.toString("utf8"));
    }
  }
  return buffer;
}

/** Build an unmasked server frame (used for pong). */
function buildFrame(opcode, payload) {
  const len = payload.length;
  let header;
  if (len < 126) {
    header = Buffer.from([0x80 | opcode, len]);
  } else if (len < 65536) {
    header = Buffer.alloc(4);
    header[0] = 0x80 | opcode;
    header[1] = 126;
    header.writeUInt16BE(len, 2);
  } else {
    header = Buffer.alloc(10);
    header[0] = 0x80 | opcode;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(len), 2);
  }
  return Buffer.concat([header, payload]);
}

function handleText(raw) {
  try {
    const p = JSON.parse(raw);
    console.log(
      JSON.stringify(
        {
          receivedAt: new Date().toISOString(),
          reason: p.reason,
          title: p.playback?.nowPlayingItem?.attributes?.name ?? p.playback?.nowPlayingItem?.title,
          artist: p.playback?.nowPlayingItem?.attributes?.artistName ?? p.playback?.nowPlayingItem?.artistName,
          lyricsFound: p.lyrics?.found,
          timing: p.lyrics?.timing,
          currentTime: p.lyrics?.currentTime,
          currentLine: p.lyrics?.currentLine?.text,
          nextLine: p.lyrics?.nextLine?.text,
          error: p.lyrics?.error,
        },
        null,
        2,
      ),
    );
  } catch {
    console.log(`[${new Date().toISOString()}] ${raw}`);
  }
}

server.listen(port, host, () => {
  console.log(`Kotonoha Cider lyrics receiver (WS) on ws://${host}:${port}${path}`);
});
