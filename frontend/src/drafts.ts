type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function loadDraft<T>(storage: DraftStorage, key: string, fallback: T): T {
  const raw = storage.getItem(key);
  if (!raw) return fallback;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === "object" &&
      !Array.isArray(parsed) &&
      fallback &&
      typeof fallback === "object" &&
      !Array.isArray(fallback)
    ) {
      return { ...(fallback as object), ...(parsed as object) } as T;
    }
    return parsed as T;
  } catch {
    return fallback;
  }
}

export function saveDraft(storage: DraftStorage, key: string, value: unknown) {
  storage.setItem(key, JSON.stringify(value));
}

export function clearDraft(storage: DraftStorage, key: string) {
  storage.removeItem(key);
}

export function loadSessionId(storage: DraftStorage, key: string): number | null {
  const id = loadDraft<{ id?: unknown }>(storage, key, {}).id;
  return Number.isInteger(id) && (id as number) > 0 ? id as number : null;
}

export function saveSessionId(storage: DraftStorage, key: string, id: number) {
  saveDraft(storage, key, { id });
}
