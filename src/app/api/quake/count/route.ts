import { NextRequest, NextResponse } from "next/server";
import { cachedFetchJson, cachedFetchText } from "@/lib/usgs-cache";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { resolvePythonBinary } from "@/lib/python-runtime";
import { errorMessage, getGlobalValue } from "@/lib/runtime-values";

const FDSN_BASE = "https://earthquake.usgs.gov/fdsnws/event/1";
const DETAIL_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail";
const execFileAsync = promisify(execFile);
const PYTHON = resolvePythonBinary();
const COUNT_CACHE_TTL_MS = 5 * 60_000;

interface CountRequest {
  mode?: "manual" | "eventid";
  eventId?: string;
  lat?: number;
  lon?: number;
  time?: string;
  radiusKm?: number;
  minMag?: number;
  startTime?: string;
  endTime?: string;
}

interface CountPayload {
  ok: boolean;
  count: number;
  cacheHit: boolean;
  localCatalog?: boolean;
  note?: string;
}

interface CatalogSpec extends Record<string, unknown> {
  start: string;
  end: string;
  minMag: number;
}

interface LocalCatalogResult {
  ok: boolean;
  localCatalog?: boolean;
  total?: number;
  events?: Array<{ latitude: number; longitude: number; time: string }>;
}

interface UsgsDetail {
  geometry: { coordinates: number[] };
  properties: { time: number };
}

const countCache = getGlobalValue("__quakeCountCache", () =>
  new Map<string, { expires: number; payload: CountPayload }>(),
);

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as CountRequest;
    let { lat, lon, time } = body;
    const { mode = "manual", eventId, radiusKm = 200, minMag = 3.0, startTime, endTime } = body;
    const requestKey = JSON.stringify({ mode, eventId, lat, lon, time, radiusKm, minMag, startTime, endTime });
    const cached = getCountCache(requestKey);
    if (cached) return NextResponse.json({ ...cached, cacheHit: true, note: `${cached.note || "数量预估"}（短期缓存）` });

    if (mode === "eventid") {
      if (!eventId) {
        return NextResponse.json({ ok: false, error: "缺少 eventId" }, { status: 400 });
      }
      const localEvent = await findLocalEvent(eventId);
      if (localEvent) {
        lon = localEvent.longitude;
        lat = localEvent.latitude;
        time = localEvent.time;
      } else {
        if (process.env.QUAKE_OFFLINE === "1") {
          return NextResponse.json({ ok: false, error: "离线目录中没有这个 Event ID" }, { status: 404 });
        }
        const detail = await cachedFetchJson<UsgsDetail>(`${DETAIL_BASE}/${eventId}.geojson`, 3600_000);
        if (detail.status >= 400) {
          return NextResponse.json({ ok: false, error: "USGS eventid 查询失败" }, { status: 502 });
        }
        const js = detail.json;
        lon = js.geometry.coordinates[0];
        lat = js.geometry.coordinates[1];
        time = new Date(js.properties.time).toISOString();
      }
    }

    if (lat == null || lon == null || !time) {
      return NextResponse.json({ ok: false, error: "缺少震中或发震时间" }, { status: 400 });
    }

    const end = endTime ? new Date(endTime) : new Date(new Date(time).getTime() - 1000);
    const localCount = await countLocalCatalog({
      lat: Number(lat),
      lon: Number(lon),
      radiusKm: Number(radiusKm),
      minMag: Number(minMag),
      start: (startTime ? new Date(startTime) : new Date(Date.UTC(1900, 0, 1))).toISOString(),
      end: end.toISOString(),
    });
    if (localCount != null) {
      const payload = {
        ok: true,
        count: localCount,
        cacheHit: false,
        localCatalog: true,
        note: "本地 SQLite 目录预估",
      };
      setCountCache(requestKey, payload);
      return NextResponse.json(payload);
    }

    if (process.env.QUAKE_OFFLINE === "1") {
      return NextResponse.json({ ok: false, error: "离线目录库不可用" }, { status: 503 });
    }

    const params = new URLSearchParams({
      latitude: String(lat),
      longitude: String(lon),
      maxradiuskm: String(radiusKm),
      minmagnitude: String(minMag),
      starttime: formatUsgsDate(startTime ? new Date(startTime) : new Date(Date.UTC(1900, 0, 1))),
      endtime: formatUsgsDate(end),
    });

    const r = await cachedFetchText(`${FDSN_BASE}/count?${params}`, 3600_000);
    if (r.status >= 400) {
      return NextResponse.json({ ok: false, error: "USGS count 查询失败" }, { status: 502 });
    }
    const payload = { ok: true, count: Number(r.text.trim()), cacheHit: Boolean(r.cacheHit) };
    setCountCache(requestKey, payload);
    return NextResponse.json(payload);
  } catch (e: unknown) {
    return NextResponse.json({ ok: false, error: errorMessage(e) }, { status: 500 });
  }
}

function getCountCache(key: string) {
  const hit = countCache.get(key);
  if (!hit) return null;
  if (hit.expires <= Date.now()) {
    countCache.delete(key);
    return null;
  }
  return hit.payload;
}

function setCountCache(key: string, payload: CountPayload) {
  countCache.set(key, { expires: Date.now() + COUNT_CACHE_TTL_MS, payload });
}

function formatUsgsDate(date: Date) {
  return date.toISOString().replace(/\.\d{3}Z$/, "");
}

async function countLocalCatalog(spec: CatalogSpec) {
  const result = await runLocalCatalog({ ...spec, countOnly: true, page: 1, pageSize: 1 });
  const total = result?.total;
  return Number.isFinite(total) ? Number(total) : null;
}

async function findLocalEvent(eventId: string) {
  const result = await runLocalCatalog({
    eventId,
    start: "1900-01-01",
    end: "2100-01-01",
    minMag: -10,
    page: 1,
    pageSize: 1,
  });
  return result?.events?.[0] || null;
}

async function runLocalCatalog(spec: Record<string, unknown>): Promise<LocalCatalogResult | null> {
  const db = await catalogDbPath();
  if (!db) return null;
  try {
    const script = path.join(process.cwd(), "scripts", "search_usgs_catalog.py");
    const { stdout } = await execFileAsync(PYTHON, [
      script,
      "--db",
      db,
      "--spec-json",
      JSON.stringify(spec),
    ], { timeout: 5000, maxBuffer: 1024 * 1024 });
    const parsed = JSON.parse(stdout) as LocalCatalogResult;
    return parsed?.ok && parsed?.localCatalog ? parsed : null;
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
