import type { Page } from "./types.ts";

export async function allPages<T>(load: (page: number) => Promise<Page<T>>): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const result = await load(page);
    items.push(...result.items);
    if (items.length >= result.total || result.items.length === 0) return items;
  }
}

export function requestScope() {
  let revision = 0;
  return {
    invalidate: () => { revision++; },
    capture: () => { const current = revision; return () => current === revision; },
  };
}
