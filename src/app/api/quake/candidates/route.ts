import { NextRequest, NextResponse } from "next/server";
import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { resolvePythonBinary } from "@/lib/python-runtime";
import { errorMessage } from "@/lib/runtime-values";

const execFileAsync = promisify(execFile);
const PYTHON = resolvePythonBinary();

export async function GET(req: NextRequest) {
  try {
    const url = new URL(req.url);
    const lat = numberParam(url, "lat");
    const lon = numberParam(url, "lon");
    const mag = numberParam(url, "mag");
    const timeUtc = url.searchParams.get("timeUtc") || "";
    const radiusKm = numberParam(url, "radiusKm") || 300;
    const text = (url.searchParams.get("text") || "").trim();

    if ((lat == null || lon == null) && !text) {
      return NextResponse.json({ ok: true, events: [], note: "缺少地点或经纬度，无法候选匹配" });
    }

    const db = await catalogDbPath();
    if (!db) {
      return NextResponse.json({ ok: true, events: [], note: "本地目录库不可用，无法按缺失年份兜底匹配" });
    }

    const script = path.join(process.cwd(), "scripts", "search_usgs_catalog.py");
    const spec = {
      candidateMatch: true,
      ...(lat != null && lon != null ? { lat, lon } : {}),
      ...(text ? { text } : {}),
      radiusKm: Math.min(1000, Math.max(20, radiusKm)),
      minMag: mag == null ? 3 : Math.max(3, mag - 0.5),
      ...(mag == null ? {} : { targetMag: mag }),
      ...(timeUtc ? { targetTimeUtc: timeUtc } : {}),
      start: "1900-01-01",
      end: new Date().toISOString().slice(0, 10),
      page: 1,
      pageSize: 8,
    };
    const { stdout } = await execFileAsync(PYTHON, [
      script,
      "--db",
      db,
      "--spec-json",
      JSON.stringify(spec),
    ], { timeout: 8000, maxBuffer: 1024 * 1024 });
    const parsed = JSON.parse(stdout);
    return NextResponse.json(parsed?.ok ? parsed : { ok: true, events: [], note: "未找到候选事件" });
  } catch (e: unknown) {
    return NextResponse.json({ ok: false, error: candidatePublicError(e) }, { status: 500 });
  }
}

function numberParam(url: URL, key: string) {
  const raw = url.searchParams.get(key);
  if (raw == null || raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
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

export function candidatePublicError(e: unknown) {
  const message = errorMessage(e);
  if (/timed out|timeout/i.test(message)) return "候选匹配超时，请手动补充年份或缩小半径";
  if (/Command failed|\/[\w.-]+\/|--spec-json|\.py\b|Traceback|JSONDecodeError/i.test(message)) {
    return "候选匹配失败，请手动确认参数后继续生成";
  }
  return message;
}
