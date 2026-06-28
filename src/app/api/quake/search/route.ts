import { NextRequest, NextResponse } from "next/server";
import { cachedFetchJson, cachedFetchText } from "@/lib/usgs-cache";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";

const FDSN_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query";
const FDSN_COUNT = "https://earthquake.usgs.gov/fdsnws/event/1/count";
const DETAIL_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail";
const PAGE_SIZE = 10;
const TEXT_CANDIDATE_LIMIT = 500;
const execFileAsync = promisify(execFile);
const PYTHON = process.env.PYTHON || "python3";
const SEARCH_CACHE_TTL_MS = 5 * 60_000;
const searchCache: Map<string, { expires: number; payload: any }> =
  ((globalThis as any).__quakeSearchCache ||= new Map());

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const q = (url.searchParams.get("q") || "").trim();
    const page = Math.max(1, Number.parseInt(url.searchParams.get("page") || "1", 10) || 1);
    if (q.length < 2) return NextResponse.json({ ok: true, events: [], page, pageSize: PAGE_SIZE, total: 0 });
    const cacheKey = `${q}\n${page}`;
    const cached = getSearchCache(cacheKey);
    if (cached) return NextResponse.json({ ...cached, cacheHit: true, note: `${cached.note || "搜索结果"}（短期缓存）` });

    const spec = parseQuery(q);
    const eventId = eventIdFromQuery(q);
    if (eventId) spec.eventId = eventId;
    const local = await searchLocalCatalog(spec, page);
    if (local) return cachedJson(cacheKey, local);

    const idEvent = eventId ? await findByEventId(eventId) : null;
    if (idEvent) return cachedJson(cacheKey, { ok: true, events: page === 1 ? [idEvent] : [], page, pageSize: PAGE_SIZE, total: 1 });

    const params = buildParams(spec);

    if (spec.text) {
      params.set("limit", String(TEXT_CANDIDATE_LIMIT));
      const fetched = await fetchEvents(params);
      const events = fetched.events;
      const term = spec.text.toLowerCase();
      const filtered = events.filter((event: any) =>
        event.place.toLowerCase().includes(term) || event.eventId.toLowerCase().includes(term)
      );
      const start = (page - 1) * PAGE_SIZE;
      return cachedJson(cacheKey, {
        ok: true,
        events: filtered.slice(start, start + PAGE_SIZE),
        page,
        pageSize: PAGE_SIZE,
        total: filtered.length,
        cacheHit: fetched.cacheHit,
        note: `地区关键字基于最近 ${TEXT_CANDIDATE_LIMIT} 条候选筛选${fetched.cacheHit ? "；结果来自缓存" : ""}`,
      });
    }

    const total = await fetchCount(params);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String((page - 1) * PAGE_SIZE + 1));
    const fetched = await fetchEvents(params);
    return cachedJson(cacheKey, {
      ok: true,
      events: fetched.events,
      page,
      pageSize: PAGE_SIZE,
      total,
      cacheHit: fetched.cacheHit,
      note: fetched.cacheHit ? "结果来自缓存" : "",
    });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message || String(e) }, { status: 500 });
  }
}

function cachedJson(key: string, payload: any) {
  searchCache.set(key, { expires: Date.now() + SEARCH_CACHE_TTL_MS, payload });
  return NextResponse.json(payload);
}

function getSearchCache(key: string) {
  const hit = searchCache.get(key);
  if (!hit) return null;
  if (hit.expires <= Date.now()) {
    searchCache.delete(key);
    return null;
  }
  return hit.payload;
}

async function searchLocalCatalog(spec: any, page: number) {
  const db = await catalogDbPath();
  if (!db) return null;
  try {
    const script = path.join(process.cwd(), "scripts", "search_usgs_catalog.py");
    const { stdout } = await execFileAsync(PYTHON, [
      script,
      "--db",
      db,
      "--spec-json",
      JSON.stringify({ ...spec, page, pageSize: PAGE_SIZE }),
    ], { timeout: 5000, maxBuffer: 1024 * 1024 });
    const parsed = JSON.parse(stdout);
    return parsed?.ok ? parsed : null;
  } catch {
    return null;
  }
}

async function catalogDbPath() {
  const candidates = [
    process.env.QUAKE_USGS_CATALOG_DB,
    path.join(process.cwd(), "var", "usgs_catalog.sqlite"),
    "/opt/quake-report-cache/usgs_catalog.sqlite",
  ].filter(Boolean) as string[];
  for (const candidate of candidates) {
    try {
      await fs.access(candidate);
      return candidate;
    } catch {
      // try next path
    }
  }
  return null;
}

function eventIdFromQuery(q: string) {
  return /^[a-z]{2}\d[\w-]{4,}$/i.test(q) ? q : "";
}

function buildParams(spec: any) {
  const params = new URLSearchParams({
      format: "geojson",
      starttime: spec.start,
      endtime: spec.end,
      minmagnitude: String(spec.minMag),
      orderby: "time",
  });
  if (spec.lat != null && spec.lon != null) {
    params.set("latitude", String(spec.lat));
    params.set("longitude", String(spec.lon));
    params.set("maxradiuskm", String(spec.radiusKm));
  }
  return params;
}

async function fetchEvents(params: URLSearchParams) {
  const r = await cachedFetchJson(`${FDSN_QUERY}?${params}`, 3600_000, {
    signal: AbortSignal.timeout(20000),
  });
  if (r.status >= 400) throw new Error(`USGS 返回 ${r.status}`);
  const json = r.json;
  return {
    events: (json.features || []).map(featureToEvent).filter(Boolean),
    cacheHit: Boolean((r as any).cacheHit),
  };
}

async function fetchCount(params: URLSearchParams) {
  const countParams = new URLSearchParams(params);
  countParams.delete("format");
  countParams.delete("orderby");
  countParams.delete("limit");
  countParams.delete("offset");
  const r = await cachedFetchText(`${FDSN_COUNT}?${countParams}`, 3600_000, {
    signal: AbortSignal.timeout(20000),
  });
  if (r.status >= 400) throw new Error(`USGS count 返回 ${r.status}`);
  return Number(r.text.trim()) || 0;
}

async function findByEventId(q: string) {
  if (!/^[a-z]{2}\d[\w-]{4,}$/i.test(q)) return null;
  const r = await cachedFetchJson(`${DETAIL_BASE}/${encodeURIComponent(q)}.geojson`, 3600_000, {
    signal: AbortSignal.timeout(10000),
  });
  if (r.status >= 400) return null;
  return featureToEvent(r.json);
}

function parseQuery(q: string) {
  const now = new Date();
  const spec: any = {
    start: "1900-01-01",
    end: now.toISOString().slice(0, 10),
    minMag: 3,
    radiusKm: 200,
    text: "",
  };
  const parts = q.replace(/，/g, ",").split(/\s+/).filter(Boolean);

  for (const part of parts) {
    const mag = part.match(/^m?(?:>=|>|=|≥)?(\d(?:\.\d)?)(?:\+)?$/i);
    if (mag) {
      spec.minMag = Math.max(3, Number(mag[1]));
      continue;
    }

    const day = part.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (day) {
      const start = new Date(`${part}T00:00:00Z`);
      const end = new Date(start.getTime() + 86400 * 1000);
      spec.start = start.toISOString().slice(0, 10);
      spec.end = end.toISOString().slice(0, 10);
      continue;
    }

    const month = part.match(/^(\d{4})-(\d{2})$/);
    if (month) {
      const start = new Date(Date.UTC(Number(month[1]), Number(month[2]) - 1, 1));
      const end = new Date(Date.UTC(Number(month[1]), Number(month[2]), 1));
      spec.start = start.toISOString().slice(0, 10);
      spec.end = end.toISOString().slice(0, 10);
      continue;
    }

    const year = part.match(/^(19|20)\d{2}$/);
    if (year) {
      spec.start = `${part}-01-01`;
      spec.end = `${Number(part) + 1}-01-01`;
      continue;
    }

    const coord = part.match(/^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/);
    if (coord) {
      spec.lat = Number(coord[1]);
      spec.lon = Number(coord[2]);
      continue;
    }

    const radius = part.match(/^r(?:adius)?=?(\d+)(?:km)?$/i);
    if (radius) {
      spec.radiusKm = Math.min(1000, Math.max(1, Number(radius[1])));
      continue;
    }

    spec.text = [spec.text, part].filter(Boolean).join(" ");
  }

  return spec;
}

function featureToEvent(feature: any) {
  const coords = feature?.geometry?.coordinates || [];
  const props = feature?.properties || {};
  if (!feature?.id || coords.length < 3 || props.mag == null || !props.time) return null;
  return {
    eventId: feature.id,
    time: new Date(props.time).toISOString(),
    latitude: Number(coords[1]),
    longitude: Number(coords[0]),
    depth: Number(coords[2]),
    mag: Number(props.mag),
    magType: props.magType || "M",
    place: props.place || "",
  };
}
