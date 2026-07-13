/**
 * POST /api/quake/generate
 *
 * 调用后端 Python CLI 生成地震报告。
 *
 * Body:
 *   {
 *     "mode": "manual" | "eventid" | "recent",
 *     "lat"?: number,
 *     "lon"?: number,
 *     "mag"?: number,
 *     "time"?: string,        // ISO8601 with Z, e.g. "2026-06-25T14:17:00Z"
 *     "depth"?: number,
 *     "place"?: string,
 *     "magType"?: string,
 *     "sourceText"?: string,
 *     "eventId"?: string,
 *     "radiusKm"?: number,
 *     "startTime"?: string,
 *     "endTime"?: string,
 *     "minMag"?: number,
 *     "figNum"?: string,
 *     "slug"?: string,
 *     "titleZh"?: string,
 *     "titleEn"?: string,
 *     "noPdf"?: boolean,
 *     "reportLevel"?: "simple" | "medium" | "full"
 *   }
 *
 * Response:
 *   {
 *     "ok": true,
 *     "files": { "map": "/api/quake/file/...", "catalog": "/api/quake/file/...", "docx": "/api/quake/file/...", "pdf": null },
 *     "fileNames": { "map": "xxx_map.png", "docx": "xxx.docx", "pdf": "xxx.pdf" },
 *     "mainshock": {...},
 *     "stats": {...}
 *   }
 */
import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import { createHash, randomUUID } from "crypto";
import path from "path";
import os from "os";
import fsSync from "fs";
import fs from "fs/promises";
import { putReportFile } from "@/lib/report-file-store";
import { resolvePythonBinary } from "@/lib/python-runtime";
import { cancelPythonWorkerJob, runPythonWorker, workerEnabled } from "@/lib/python-worker";
import { errorMessage, getGlobalValue } from "@/lib/runtime-values";

const PROJECT_ROOT = process.cwd();
const CLI_SCRIPT = path.join(PROJECT_ROOT, "scripts", "quake_report", "cli.py");
const MIME: Record<string, string> = {
  ".png": "image/png",
  ".csv": "text/csv; charset=utf-8",
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};
const GENERATION_CACHE_TTL_MS = 10 * 60_000;

interface GenerationRequest {
  mode?: "manual" | "eventid" | "recent";
  lat?: number;
  lon?: number;
  mag?: number;
  time?: string;
  depth?: number;
  place?: string;
  magType?: string;
  sourceText?: string;
  eventId?: string;
  radiusKm?: number;
  startTime?: string;
  endTime?: string;
  minMag?: number;
  figNum?: string;
  slug?: string;
  titleZh?: string;
  titleEn?: string;
  noPdf?: boolean;
  reportLevel?: unknown;
  tz?: string;
  mapView?: string;
  stream?: boolean;
}

interface SummaryItem {
  files: {
    map?: string | null;
    catalog?: string | null;
    docx?: string | null;
    pdf?: string | null;
  };
  mainshock?: Record<string, unknown>;
  event_id?: string;
  latitude?: number;
  longitude?: number;
  depth_km?: number;
  magnitude?: number;
  mag_type?: string;
  time_utc?: string;
  place?: string;
  stats?: Record<string, unknown>;
  mapMeta?: Record<string, unknown>;
  warnings?: string[];
}

type GenerationResult = ReturnType<typeof buildResultPayload>;

const generationCache = getGlobalValue("__quakeGenerationCache", () =>
  new Map<string, { expires: number; result: GenerationResult }>(),
);
const generateRequests = getGlobalValue("__quakeGenerateRequests", () =>
  new Map<string, number[]>(),
);

export async function POST(req: NextRequest) {
  try {
    const retryAfter = rateLimitRetryAfter(req);
    if (retryAfter > 0) {
      return NextResponse.json(
        { ok: false, error: "生成请求过于频繁，请稍后重试" },
        { status: 429, headers: { "Retry-After": String(retryAfter) } },
      );
    }
    const body = (await req.json()) as GenerationRequest;
    const {
      mode = "manual",
      lat, lon, mag, time, depth, place, magType, sourceText,
      eventId,
      radiusKm = 200, startTime, endTime, minMag = 3.0,
      figNum = "1", slug, titleZh, titleEn,
      noPdf = false, reportLevel: rawReportLevel,
      tz = "utc", mapView = "mag",
    } = body;
    const reportLevel = normalizeReportLevel(rawReportLevel);
    const cacheKey = generationCacheKey({
      mode, lat, lon, mag, time, depth, place, magType, sourceText, eventId,
      radiusKm, startTime, endTime, minMag, figNum, slug, titleZh, titleEn,
      noPdf, reportLevel, tz, mapView,
    });
    const cached = getGenerationCache(cacheKey);
    if (cached) {
      return body.stream
        ? streamCachedResult(cached)
        : NextResponse.json({ ...cached, cacheHit: true, note: "参数未变，复用最近一次生成结果" });
    }

    // 构造 CLI 参数
    const args: string[] = ["--mode", mode];

    if (mode === "manual") {
      if (lat == null || lon == null || mag == null || !time) {
        return NextResponse.json(
          { ok: false, error: "manual 模式需要 lat/lon/mag/time 四个参数" },
          { status: 400 }
        );
      }
      args.push("--lat", String(lat));
      args.push("--lon", String(lon));
      args.push("--mag", String(mag));
      args.push("--time", time);
      if (depth != null) args.push("--depth", String(depth));
      if (magType) args.push("--mag-type", magType);
    } else if (mode === "eventid") {
      if (!eventId) {
        return NextResponse.json(
          { ok: false, error: "eventid 模式需要 eventId 参数" },
          { status: 400 }
        );
      }
      args.push("--event-id", eventId);
    } else if (mode === "recent") {
      // 用默认参数即可
    } else {
      return NextResponse.json(
        { ok: false, error: `不支持的 mode: ${mode}` },
        { status: 400 }
      );
    }

    args.push("--radius-km", String(radiusKm));
    if (place) args.push("--place", place);
    if (sourceText) args.push("--source-text", sourceText);
    if (startTime) args.push("--start-time", startTime);
    if (endTime) args.push("--end-time", endTime);
    args.push("--min-mag", String(minMag));

    if (slug) args.push("--slug", slug);
    args.push("--fig-num", figNum);
    if (titleZh) args.push("--title-zh", titleZh);
    if (titleEn) args.push("--title-en", titleEn);

    args.push("--no-pdf");
    args.push("--report-level", reportLevel);
    if (tz) args.push("--tz", tz);
    if (mapView) args.push("--map-view", mapView);

    const outputDir = await fs.mkdtemp(path.join(os.tmpdir(), "quake-report-"));
    args.push("--output-dir", outputDir);
    // 输出 JSON 摘要到临时文件
    const jsonPath = path.join(outputDir, "summary.json");
    args.push("--json-summary", jsonPath);

    if (body.stream) {
      return streamPython(CLI_SCRIPT, args, jsonPath, outputDir, !noPdf, cacheKey);
    }

    // 调用 Python
    const result = await runPython(CLI_SCRIPT, args);

    // 读取摘要
    let summary: SummaryItem[] | null = null;
    try {
      const txt = await fs.readFile(jsonPath, "utf-8");
      summary = JSON.parse(txt) as SummaryItem[];
      await fs.unlink(jsonPath).catch(() => {});
    } catch {
      // ignore
    }

    if (result.code !== 0) {
      await cleanupOutput(outputDir);
      return NextResponse.json(
        {
          ok: false,
          error: formatCliError(result),
        },
        { status: 500 }
      );
    }

    if (!summary || !summary[0]) {
      await cleanupOutput(outputDir);
      return NextResponse.json(
        {
          ok: false,
          error: "生成失败：未获取到报告摘要",
        },
        { status: 500 }
      );
    }

    const item = summary[0];
    try {
      const payload = buildResultPayload(item, !noPdf);
      setGenerationCache(cacheKey, payload);
      return NextResponse.json(payload);
    } finally {
      await cleanupOutput(outputDir);
    }
  } catch (e: unknown) {
    return NextResponse.json(
      { ok: false, error: errorMessage(e) },
      { status: 500 }
    );
  }
}

function generationCacheKey(value: Record<string, unknown>) {
  return createHash("sha1").update(JSON.stringify(value)).digest("hex");
}

function normalizeReportLevel(value: unknown) {
  if (value === "simple" || value === "medium" || value === "full") return value;
  return "simple";
}

function getGenerationCache(key: string) {
  const hit = generationCache.get(key);
  if (!hit) return null;
  if (hit.expires <= Date.now()) {
    generationCache.delete(key);
    return null;
  }
  return hit.result;
}

function setGenerationCache(key: string, result: GenerationResult) {
  generationCache.set(key, { expires: Date.now() + GENERATION_CACHE_TTL_MS, result });
}

function streamCachedResult(result: GenerationResult) {
  const encoder = new TextEncoder();
  const body =
    `${JSON.stringify({ type: "progress", progress: 100, message: "参数未变，复用最近一次生成结果" })}\n` +
    `${JSON.stringify({ type: "done", progress: 100, result: { ...result, cacheHit: true, note: "参数未变，复用最近一次生成结果" } })}\n`;
  return new Response(encoder.encode(body), {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    },
  });
}

function buildResultPayload(item: SummaryItem, canPdf = true) {
  const map = toStoredFile(item.files.map, false);
  const catalog = toStoredFile(item.files.catalog, true);
  const docx = toStoredFile(item.files.docx, true);
  const pdf = toStoredFile(item.files.pdf, true);
  const publicMainshock = item.mainshock ?? {
    event_id: item.event_id,
    latitude: item.latitude,
    longitude: item.longitude,
    depth_km: item.depth_km,
    magnitude: item.magnitude,
    mag_type: item.mag_type,
    time_utc: item.time_utc,
    place: item.place,
  };
  return {
    ok: true,
    files: {
      map: map?.url ?? null,
      catalog: catalog?.downloadUrl ?? null,
      docx: docx?.downloadUrl ?? null,
      pdf: pdf?.downloadUrl ?? null,
    },
    fileNames: {
      map: map?.fileName ?? null,
      catalog: catalog?.fileName ?? null,
      docx: docx?.fileName ?? null,
      pdf: pdf?.fileName ?? null,
    },
    fileRefs: { map, catalog, docx, pdf },
    mainshock: publicMainshock,
    stats: item.stats,
    mapMeta: item.mapMeta,
    warnings: item.warnings || [],
    canPdf: canPdf && Boolean(docx),
  };
}

function toStoredFile(p: string | null | undefined, downloadOnly: boolean) {
  if (!p) return null;
  const ext = path.extname(p).toLowerCase();
  const mime = MIME[ext] || "application/octet-stream";
  const fileName = path.basename(p);
  const buffer = fsSync.readFileSync(p);
  const id = putReportFile(buffer, fileName, mime);
  const baseUrl = `/api/quake/file/${id}`;
  return {
    id,
    fileName,
    mime,
    size: buffer.length,
    url: downloadOnly ? `${baseUrl}?download=1` : `${baseUrl}?download=0`,
    downloadUrl: `${baseUrl}?download=1`,
  };
}

async function cleanupOutput(outputDir: string) {
  await fs.rm(outputDir, { recursive: true, force: true }).catch(() => {});
}

function streamPython(script: string, args: string[], jsonPath: string, outputDir: string, canPdf: boolean, cacheKey: string) {
  const encoder = new TextEncoder();
  let stdout = "";
  let stderr = "";
  let pending = "";
  const jobId = randomUUID();
  let proc: ReturnType<typeof spawn> | null = null;
  let usingWorker = false;
  let finished = false;

  const stream = new ReadableStream({
    start(controller) {
      const startedAt = Date.now();
      let lastStageAt = startedAt;
      const send = (payload: unknown) => {
        if (finished) return false;
        try {
          controller.enqueue(encoder.encode(`${JSON.stringify(payload)}\n`));
          return true;
        } catch {
          finished = true;
          proc?.kill("SIGTERM");
          void cleanupOutput(outputDir);
          return false;
        }
      };
      const finish = async (payload: unknown) => {
        if (finished) return;
        finished = true;
        try {
          controller.enqueue(encoder.encode(`${JSON.stringify(payload)}\n`));
        } catch {
          // Browser disconnected; cleanup below is still required.
        }
        await cleanupOutput(outputDir);
        try {
          controller.close();
        } catch {
          // Already closed.
        }
      };
      const onLine = (line: string) => {
        if (line.startsWith("MAP_READY:")) {
          const mapPath = line.slice("MAP_READY:".length).trim();
          try {
            const file = toStoredFile(mapPath, false);
            send({
              type: "map_preview",
              progress: 58,
              message: "分布图已生成，继续写入报告",
              file,
              map: file?.url ?? null,
              fileName: file?.fileName ?? null,
              elapsedSec: (Date.now() - startedAt) / 1000,
            });
          } catch {
            send({ type: "progress", progress: 58, message: "分布图已生成，继续写入报告" });
          }
          return;
        }
        const stage = line.match(/\[(\d+)\/(\d+)\]\s*(.+)/);
        if (stage) {
          const now = Date.now();
          const step = Number(stage[1]);
          const total = Number(stage[2]);
          const stageProgress = [0, 18, 42, 60, 78, 92][step] ?? Math.round(((step - 1) / total) * 100);
          send({
            type: "progress",
            progress: stageProgress,
            message: stage[3].replace(/\s*→.*/, "").trim(),
            step,
            total,
            elapsedSec: (now - startedAt) / 1000,
            stepElapsedSec: (now - lastStageAt) / 1000,
          });
          lastStageAt = now;
        } else if (line.includes("→ 命中")) {
          send({ type: "log", progress: 30, message: line.trim(), elapsedSec: (Date.now() - startedAt) / 1000 });
        }
      };

      const closeJob = async (code: number | null) => {
          if (finished) return;
          if (pending) onLine(pending);
          if (code !== 0) {
            await finish({
              type: "done",
              result: { ok: false, error: formatCliError({ stdout, stderr }) },
            });
            return;
          }

          try {
            const txt = await fs.readFile(jsonPath, "utf-8");
            const summary = JSON.parse(txt) as SummaryItem[];
            await fs.unlink(jsonPath).catch(() => {});
            const item = summary?.[0];
            if (!item) throw new Error("未获取到生成摘要");
            const result = buildResultPayload(item, canPdf);
            setGenerationCache(cacheKey, result);
            await finish({
              type: "done",
              progress: 100,
              result,
            });
          } catch {
            await finish({
              type: "done",
              result: { ok: false, error: "生成失败：未获取到报告摘要" },
            });
          }
      };

      try {
        if (workerEnabled()) {
          usingWorker = true;
          runPythonWorker(args, {
            onQueued: (queuePosition) => {
              send({
                type: "job",
                jobId,
                progress: queuePosition > 1 ? 2 : 5,
                message: queuePosition > 1 ? "任务已进入生成队列" : "任务开始执行",
                queuePosition,
                waitSec: 0,
              });
            },
            onStart: () => {
              lastStageAt = Date.now();
              send({
                type: "progress",
                progress: 5,
                message: "任务开始执行",
                queuePosition: 1,
                waitSec: (Date.now() - startedAt) / 1000,
              });
            },
            onStdoutLine: onLine,
            onStderrLine: (line) => {
              stderr += `${line}\n`;
            },
          }, jobId).then(async (result) => {
            stdout = result.stdout;
            stderr = result.stderr;
            await closeJob(result.code);
          });
          return;
        }

        send({ type: "job", jobId, progress: 5, message: "任务开始执行", waitSec: 0 });
        const python = resolvePythonBinary();
        const child = spawn(python, [script, ...args], {
          env: { ...process.env, PYTHONUNBUFFERED: "1", MPLCONFIGDIR: process.env.MPLCONFIGDIR || path.join(os.tmpdir(), "quake-report-mpl") },
        });
        proc = child;

        child.stdout.on("data", (d) => {
          const text = d.toString();
          stdout += text;
          pending += text;
          const lines = pending.split(/\r?\n/);
          pending = lines.pop() || "";
          for (const line of lines) onLine(line);
        });
        child.stderr.on("data", (d) => {
          stderr += d.toString();
        });
        child.on("error", async (e) => {
          stderr += `${e?.message || String(e)}\n`;
          await finish({
            type: "done",
            result: { ok: false, error: formatCliError({ stdout, stderr }) },
          });
        });
        child.on("close", closeJob);
      } catch (e: unknown) {
        void finish({ type: "done", result: { ok: false, error: errorMessage(e) } });
      }
    },
    cancel() {
      finished = true;
      proc?.kill("SIGTERM");
      if (usingWorker) cancelPythonWorkerJob(jobId);
      void cleanupOutput(outputDir);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Accel-Buffering": "no",
    },
  });
}

function rateLimitRetryAfter(req: NextRequest) {
  const limit = Number(process.env.QUAKE_RATE_LIMIT_PER_MINUTE || 0);
  if (!Number.isFinite(limit) || limit <= 0) return 0;
  const now = Date.now();
  const key = req.headers.get("cf-connecting-ip")
    || req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
    || "unknown";
  const recent = (generateRequests.get(key) || []).filter((time) => now - time < 60_000);
  if (recent.length >= limit) {
    generateRequests.set(key, recent);
    return Math.max(1, Math.ceil((60_000 - (now - recent[0])) / 1000));
  }
  recent.push(now);
  generateRequests.set(key, recent);
  return 0;
}

function formatCliError(result: { stdout: string; stderr: string }) {
  if (result.stderr.includes("中国区域地图需要国内官方边界数据")) {
    return "当前事件位于中国区域，出图需要国内官方边界数据：请上传 BOUL 边界文件，或放入天地图行政区划 GeoJSON 缓存；未安装前不会使用非官方国界线替代。";
  }

  const runtimeError = result.stderr.match(/RuntimeError:\s*([^\n]+)/);
  if (runtimeError?.[1]) return runtimeError[1].trim();

  const cliError = result.stderr.match(/quake_report:\s*error:\s*([^\n]+)/);
  if (cliError?.[1]) return cliError[1].trim();

  const lastLine = result.stderr
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .at(-1);

  return lastLine || "Python CLI 退出码非 0";
}

function runPython(script: string, args: string[]): Promise<{
  code: number;
  stdout: string;
  stderr: string;
}> {
  if (workerEnabled()) return runPythonWorker(args);
  return new Promise((resolve) => {
    const python = resolvePythonBinary();
    const proc = spawn(python, [script, ...args], {
      env: { ...process.env, PYTHONUNBUFFERED: "1", MPLCONFIGDIR: process.env.MPLCONFIGDIR || path.join(os.tmpdir(), "quake-report-mpl") },
    });
    let settled = false;
    let stdout = "";
    let stderr = "";
    const finish = (code: number) => {
      if (settled) return;
      settled = true;
      resolve({ code, stdout, stderr });
    };
    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));
    proc.on("error", (e) => {
      stderr += `${e?.message || String(e)}\n`;
      finish(-1);
    });
    proc.on("close", (code) => finish(code ?? -1));
  });
}
