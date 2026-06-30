/**
 * GET /api/quake/recent
 *
 * 返回近 N 天 M≥X 的全球地震列表，用于"拉取 USGS 最新大震"模式。
 *
 * Query:
 *   days?: number (default 30)
 *   minMag?: number (default 6.0)
 *   limit?: number (default 30)
 */
import { NextRequest, NextResponse } from "next/server";
import { cachedFetchText } from "@/lib/usgs-cache";

const USGS_FDSN = "https://earthquake.usgs.gov/fdsnws/event/1/query";

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const requestedDays = Number(url.searchParams.get("days") || 30);
    const requestedMinMag = Number(url.searchParams.get("minMag") || 6.0);
    const requestedLimit = Number(url.searchParams.get("limit") || 30);
    const days = [20, 30, 40, 50].includes(requestedDays) ? requestedDays : 30;
    const minMag = [4, 5, 6, 7, 8, 9].includes(requestedMinMag) ? requestedMinMag : 6;
    const limit = Math.min(50, Math.max(20, Math.floor(requestedLimit) || 30));

    const end = new Date();
    const start = new Date(end.getTime() - days * 86400 * 1000);

    const params = new URLSearchParams({
      format: "csv",
      starttime: start.toISOString().slice(0, 10),
      endtime: end.toISOString().slice(0, 10),
      minmagnitude: String(minMag),
      orderby: "time",
    });

    const r = await cachedFetchText(
      `${USGS_FDSN}?${params.toString()}`,
      600_000,
      { signal: AbortSignal.timeout(30000) },
      6 * 3600_000
    );
    if (r.status >= 400) {
      return NextResponse.json(
        { ok: false, error: `USGS 返回 ${r.status}` },
        { status: 502 }
      );
    }
    const csv = r.text;
    const events = parseCsv(csv).slice(0, limit).map((row: any) => ({
      eventId: row.id,
      time: row.time,
      latitude: Number(row.latitude),
      longitude: Number(row.longitude),
      depth: Number(row.depth),
      mag: Number(row.mag),
      magType: row.magType,
      place: row.place,
    }));

    return NextResponse.json({ ok: true, events, cacheHit: Boolean(r.cacheHit), cacheStale: Boolean(r.stale) });
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message || String(e) },
      { status: 500 }
    );
  }
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/);
  if (lines.length < 2) return [];
  const headers = splitCsvLine(lines[0]).map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line);
    const obj: Record<string, string> = {};
    headers.forEach((h, i) => (obj[h] = (cells[i] || "").trim()));
    return obj;
  });
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === "\"") {
      if (quoted && line[i + 1] === "\"") {
        cell += "\"";
        i++;
      } else {
        quoted = !quoted;
      }
    } else if (ch === "," && !quoted) {
      cells.push(cell);
      cell = "";
    } else {
      cell += ch;
    }
  }
  cells.push(cell);
  return cells;
}
