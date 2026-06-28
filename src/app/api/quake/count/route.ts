import { NextRequest, NextResponse } from "next/server";
import { cachedFetchJson, cachedFetchText } from "@/lib/usgs-cache";

const FDSN_BASE = "https://earthquake.usgs.gov/fdsnws/event/1";
const DETAIL_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    let { lat, lon, time } = body;
    const { mode = "manual", eventId, radiusKm = 200, minMag = 3.0, startTime, endTime } = body;

    if (mode === "eventid") {
      if (!eventId) {
        return NextResponse.json({ ok: false, error: "缺少 eventId" }, { status: 400 });
      }
      const detail = await cachedFetchJson(`${DETAIL_BASE}/${eventId}.geojson`, 3600_000);
      if (detail.status >= 400) {
        return NextResponse.json({ ok: false, error: "USGS eventid 查询失败" }, { status: 502 });
      }
      const js = detail.json;
      lon = js.geometry.coordinates[0];
      lat = js.geometry.coordinates[1];
      time = new Date(js.properties.time).toISOString();
    }

    if (lat == null || lon == null || !time) {
      return NextResponse.json({ ok: false, error: "缺少震中或发震时间" }, { status: 400 });
    }

    const end = endTime ? new Date(endTime) : new Date(new Date(time).getTime() - 1000);
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
    return NextResponse.json({ ok: true, count: Number(r.text.trim()), cacheHit: Boolean(r.cacheHit) });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message || String(e) }, { status: 500 });
  }
}

function formatUsgsDate(date: Date) {
  return date.toISOString().replace(/\.\d{3}Z$/, "");
}
