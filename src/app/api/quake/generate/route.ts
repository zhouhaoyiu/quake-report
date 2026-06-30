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

const PROJECT_ROOT = process.cwd();
const CLI_SCRIPT = path.join(PROJECT_ROOT, "scripts", "quake_report", "cli.py");
const MIME: Record<string, string> = {
  ".png": "image/png",
  ".csv": "text/csv; charset=utf-8",
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};
let jobQueue = Promise.resolve();
let queuedJobs = 0;
let runningJobs = 0;
const GENERATION_CACHE_TTL_MS = 10 * 60_000;
const generationCache: Map<string, { expires: number; result: any }> =
  ((globalThis as any).__quakeGenerationCache ||= new Map());

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      mode = "manual",
      lat, lon, mag, time, depth, place, magType,
      eventId,
      radiusKm = 200, startTime, endTime, minMag = 3.0,
      figNum = "1", slug, titleZh, titleEn,
      noPdf = false, reportLevel: rawReportLevel,
      tz = "utc", mapView = "mag",
    } = body;
    const reportLevel = normalizeReportLevel(rawReportLevel);
    const cacheKey = generationCacheKey({
      mode, lat, lon, mag, time, depth, place, magType, eventId,
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
    const result = await enqueueJob(() => runPython(CLI_SCRIPT, args));

    // 读取摘要
    let summary: any = null;
    try {
      const txt = await fs.readFile(jsonPath, "utf-8");
      summary = JSON.parse(txt);
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
  } catch (e: any) {
    return NextResponse.json(
      { ok: false, error: e?.message || String(e) },
      { status: 500 }
    );
  }
}

function generationCacheKey(value: any) {
  return createHash("sha1").update(JSON.stringify(value)).digest("hex");
}

function normalizeReportLevel(value: any) {
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

function setGenerationCache(key: string, result: any) {
  generationCache.set(key, { expires: Date.now() + GENERATION_CACHE_TTL_MS, result });
}

function streamCachedResult(result: any) {
  const encoder = new TextEncoder();
  const body =
    `${JSON.stringify({ type: "progress", progress: 100, message: "参数未变，复用最近一次生成结果" })}\n` +
    `${JSON.stringify({ type: "done", progress: 100, result: { ...result, cacheHit: true, note: "参数未变，复用最近一次生成结果" } })}\n`;
  return new Response(encoder.encode(body), {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function buildResultPayload(item: any, canPdf = true) {
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

  const stream = new ReadableStream({
    start(controller) {
      const queuedAt = Date.now();
      let startedAt = queuedAt;
      let lastStageAt = queuedAt;
      const send = (payload: any) => {
        controller.enqueue(encoder.encode(`${JSON.stringify(payload)}\n`));
      };
      send({
        type: "job",
        jobId,
        progress: 2,
        message: "任务已进入生成队列",
        queuePosition: getQueuePosition(),
      });

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

      enqueueJob(() => new Promise<void>((resolve) => {
        startedAt = Date.now();
        lastStageAt = startedAt;
        send({
          type: "progress",
          progress: 5,
          message: "任务开始执行",
          waitSec: (startedAt - queuedAt) / 1000,
        });
        const python = resolvePythonBinary();
        const proc = spawn(python, [script, ...args], {
          env: { ...process.env, PYTHONUNBUFFERED: "1" },
        });

        proc.stdout.on("data", (d) => {
          const text = d.toString();
          stdout += text;
          pending += text;
          const lines = pending.split(/\r?\n/);
          pending = lines.pop() || "";
          for (const line of lines) onLine(line);
        });
        proc.stderr.on("data", (d) => {
          stderr += d.toString();
        });
        proc.on("close", async (code) => {
          if (pending) onLine(pending);
          if (code !== 0) {
            send({
              type: "done",
              result: { ok: false, error: formatCliError({ stdout, stderr }) },
            });
            await cleanupOutput(outputDir);
            controller.close();
            resolve();
            return;
          }

          try {
            const txt = await fs.readFile(jsonPath, "utf-8");
            const summary = JSON.parse(txt);
            await fs.unlink(jsonPath).catch(() => {});
            const item = summary?.[0];
            if (!item) throw new Error("未获取到生成摘要");
            const result = buildResultPayload(item, canPdf);
            setGenerationCache(cacheKey, result);
            send({
              type: "done",
              progress: 100,
              result,
            });
          } catch (e: any) {
            send({
              type: "done",
              result: { ok: false, error: "生成失败：未获取到报告摘要" },
            });
          } finally {
            await cleanupOutput(outputDir);
            controller.close();
            resolve();
          }
        });
      })).catch(async (e) => {
        send({ type: "done", result: { ok: false, error: e?.message || String(e) } });
        await cleanupOutput(outputDir);
        controller.close();
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "application/x-ndjson; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function enqueueJob<T>(work: () => Promise<T>) {
  queuedJobs += 1;
  const runWork = async () => {
    queuedJobs = Math.max(0, queuedJobs - 1);
    runningJobs += 1;
    try {
      return await work();
    } finally {
      runningJobs = Math.max(0, runningJobs - 1);
    }
  };
  const run = jobQueue.then(runWork, runWork);
  jobQueue = run.then(() => undefined, () => undefined);
  return run;
}

function getQueuePosition() {
  return runningJobs + queuedJobs + 1;
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
  return new Promise((resolve) => {
    const python = resolvePythonBinary();
    const proc = spawn(python, [script, ...args], {
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));
    proc.on("close", (code) =>
      resolve({ code: code ?? -1, stdout, stderr })
    );
  });
}
