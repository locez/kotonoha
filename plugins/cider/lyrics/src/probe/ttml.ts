import type { TimedLyricLine, TimedLyricWord } from "./types";

const XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace";

type ParseOptions = {
  durationSeconds?: number | null;
  preferredTranslationLanguage?: string;
};

export type ParsedTtml = {
  timing: string | null;
  language: string | null;
  lines: TimedLyricLine[];
};

function compactText(value: string | null | undefined): string {
  return (value ?? "").replace(/\s+/g, " ").trim();
}

function parseTime(value: string | null | undefined): number | null {
  if (!value) {
    return null;
  }

  const text = value.trim().replace(",", ".");
  if (!text) {
    return null;
  }

  if (text.endsWith("s")) {
    const seconds = Number(text.slice(0, -1));
    return Number.isFinite(seconds) ? roundTime(seconds) : null;
  }

  const parts = text.split(":").map(Number);
  if (parts.some((part) => !Number.isFinite(part))) {
    return null;
  }

  if (parts.length === 3) {
    return roundTime(parts[0] * 3600 + parts[1] * 60 + parts[2]);
  }

  if (parts.length === 2) {
    return roundTime(parts[0] * 60 + parts[1]);
  }

  if (parts.length === 1) {
    return roundTime(parts[0]);
  }

  return null;
}

function roundTime(value: number): number {
  return Math.floor(value * 1000) / 1000;
}

function xmlAttribute(element: Element, name: string): string {
  return element.getAttribute(`xml:${name}`) || element.getAttributeNS(XML_NAMESPACE, name) || "";
}

function elementsByName(root: Document | Element, name: string): Element[] {
  return Array.from(root.getElementsByTagNameNS("*", name));
}

function collectTranslations(documentRef: Document, language: string): Record<string, string> {
  const translations: Record<string, string> = {};

  for (const translation of elementsByName(documentRef, "translation")) {
    const translationLanguage = xmlAttribute(translation, "lang") || "unknown";
    if (translationLanguage !== language) {
      continue;
    }

    for (const text of elementsByName(translation, "text")) {
      const targetId = text.getAttribute("for");
      if (targetId) {
        translations[targetId] = compactText(text.textContent);
      }
    }
  }

  return translations;
}

function extractWords(lineElement: Element): TimedLyricWord[] {
  return elementsByName(lineElement, "span")
    .map((span) => ({
      start: parseTime(span.getAttribute("begin")),
      end: parseTime(span.getAttribute("end")),
      text: compactText(span.textContent),
    }))
    .filter((word) => word.text);
}

export function parseAppleMusicTtml(ttml: string, options: ParseOptions = {}): ParsedTtml {
  const documentRef = new DOMParser().parseFromString(ttml, "text/xml");
  const parserError = documentRef.querySelector("parsererror");
  if (parserError) {
    throw new Error(compactText(parserError.textContent) || "Failed to parse TTML");
  }

  const translationLanguage = options.preferredTranslationLanguage ?? "zh-Hans";
  const translations = collectTranslations(documentRef, translationLanguage);
  const durationSeconds =
    typeof options.durationSeconds === "number" && Number.isFinite(options.durationSeconds)
      ? options.durationSeconds
      : null;

  const rawLines = elementsByName(documentRef, "p")
    .map((lineElement, index) => {
      const id = xmlAttribute(lineElement, "id") || lineElement.getAttribute("id") || `L${index + 1}`;
      return {
        index,
        id,
        start: parseTime(lineElement.getAttribute("begin")),
        rawEnd: parseTime(lineElement.getAttribute("end")),
        text: compactText(lineElement.textContent),
        translation: translations[id] ?? "",
        words: extractWords(lineElement),
      };
    })
    .filter((line) => line.text && line.start !== null);

  const lines: TimedLyricLine[] = rawLines.map((line, index) => {
    const nextStart = rawLines[index + 1]?.start ?? null;
    const rawEndIsUsable =
      line.rawEnd !== null &&
      line.rawEnd > line.start! &&
      (durationSeconds === null || line.rawEnd <= durationSeconds + 10);

    return {
      index: line.index,
      id: line.id,
      start: line.start!,
      end: rawEndIsUsable ? line.rawEnd! : nextStart ?? durationSeconds ?? line.start!,
      text: line.text,
      translation: line.translation,
      words: line.words,
    };
  });

  return {
    timing: documentRef.documentElement.getAttribute("itunes:timing"),
    language: xmlAttribute(documentRef.documentElement, "lang") || null,
    lines,
  };
}

export function findCurrentLine(lines: TimedLyricLine[], currentTime: number | null | undefined): TimedLyricLine | null {
  if (typeof currentTime !== "number" || !Number.isFinite(currentTime)) {
    return null;
  }

  return lines.find((line) => line.start <= currentTime && currentTime < line.end) ?? null;
}
