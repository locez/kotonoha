const APPLIED_PLUGINS_KEY = "c3api/applied-plugins";

type StringStorage = {
  get(key: string): string | undefined;
  set(key: string, value: string): unknown;
};

export type DedupeResult = {
  changed: boolean;
  before: number;
  after: number;
};

export function dedupeAppliedPluginList(storage: StringStorage, pluginId: string): DedupeResult {
  const raw = storage.get(APPLIED_PLUGINS_KEY);
  if (!raw) {
    return { changed: false, before: 0, after: 0 };
  }

  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return { changed: false, before: 0, after: 0 };
  }

  if (!Array.isArray(value)) {
    return { changed: false, before: 0, after: 0 };
  }

  const before = value.length;
  const seen = new Set<string>();
  const deduped = value.filter((entry) => {
    if (typeof entry !== "string") {
      return true;
    }

    if (entry !== pluginId) {
      return true;
    }

    if (seen.has(entry)) {
      return false;
    }

    seen.add(entry);
    return true;
  });

  if (deduped.length === before) {
    return { changed: false, before, after: before };
  }

  storage.set(APPLIED_PLUGINS_KEY, JSON.stringify(deduped));
  return { changed: true, before, after: deduped.length };
}

export function dedupeBrowserAppliedPluginList(pluginId: string): DedupeResult {
  return dedupeAppliedPluginList(
    {
      get: (key) => window.localStorage.getItem(key) ?? undefined,
      set: (key, value) => window.localStorage.setItem(key, value),
    },
    pluginId,
  );
}
