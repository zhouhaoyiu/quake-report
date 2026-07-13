import { getGlobalValue } from "@/lib/runtime-values";

type Entry = { expires: number; text: string; status: number; cacheHit?: boolean; stale?: boolean };

const store = getGlobalValue("__quakeUsgsCache", () => new Map<string, Entry>());

export async function cachedFetchText(url: string, ttlMs: number, init?: RequestInit, staleMs = 0) {
  const key = `${url}`;
  const now = Date.now();
  const hit = store.get(key);
  if (hit && hit.expires > now) return { ...hit, cacheHit: true };
  const staleHit = hit && staleMs > 0 && now - hit.expires <= staleMs;

  try {
    const res = await fetch(url, { ...init, cache: "no-store" });
    const text = await res.text();
    const entry = { status: res.status, text, expires: now + ttlMs };
    if (res.ok) store.set(key, entry);
    if (!res.ok && res.status >= 500 && staleHit) return { ...hit, cacheHit: true, stale: true };
    return { ...entry, cacheHit: false };
  } catch (error) {
    if (staleHit) return { ...hit, cacheHit: true, stale: true };
    throw error;
  }
}

export async function cachedFetchJson<T = unknown>(url: string, ttlMs: number, init?: RequestInit) {
  const res = await cachedFetchText(url, ttlMs, init);
  try {
    return { status: res.status, json: JSON.parse(res.text) as T, cacheHit: Boolean(res.cacheHit) };
  } catch {
    throw new Error("上游服务返回格式异常，请稍后重试");
  }
}
