import { createServer } from "node:http";

const host = "127.0.0.1";
const port = Number.parseInt(process.env.CIDER_LYRICS_PROBE_PORT ?? "28745", 10);
const path = "/kotonoha/cider/lyrics";

const server = createServer((req, res) => {
  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    });
    res.end();
    return;
  }

  if (req.method !== "POST" || req.url !== path) {
    res.writeHead(404, {
      "Access-Control-Allow-Origin": "*",
      "Content-Type": "text/plain; charset=utf-8",
    });
    res.end("not found");
    return;
  }

  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    const raw = Buffer.concat(chunks).toString("utf8");
    const receivedAt = new Date().toISOString();

    try {
      const payload = JSON.parse(raw);
      console.log(
        JSON.stringify(
          {
            receivedAt,
            title: payload.playback?.nowPlayingItem?.attributes?.name ?? payload.playback?.nowPlayingItem?.title,
            artist: payload.playback?.nowPlayingItem?.attributes?.artistName ?? payload.playback?.nowPlayingItem?.artistName,
            lyricsFound: payload.lyrics?.found,
            songId: payload.lyrics?.songId,
            timing: payload.lyrics?.timing,
            language: payload.lyrics?.language,
            lineCount: payload.lyrics?.lineCount ?? 0,
            currentTime: payload.lyrics?.currentTime,
            currentLine: payload.lyrics?.currentLine,
            previousLine: payload.lyrics?.previousLine,
            nextLine: payload.lyrics?.nextLine,
            aroundLines: payload.lyrics?.aroundLines,
            error: payload.lyrics?.error,
            playback: payload.playback,
          },
          null,
          2,
        ),
      );
    } catch {
      console.log(`[${receivedAt}] ${raw}`);
    }

    res.writeHead(204, {
      "Access-Control-Allow-Origin": "*",
    });
    res.end();
  });
});

server.listen(port, host, () => {
  console.log(`Kotonoha Cider lyrics receiver listening on http://${host}:${port}${path}`);
});
