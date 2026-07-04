import { NextResponse } from "next/server";
import fs from "fs/promises";
import path from "path";
import { prewarmPythonWorker } from "@/lib/python-worker";

const STATUS_PATHS = [
  process.env.QUAKE_USGS_CATALOG_STATUS,
  path.join(process.cwd(), "var", "usgs_catalog_status.json"),
].filter(Boolean) as string[];

export async function GET() {
  prewarmPythonWorker();
  for (const file of STATUS_PATHS) {
    try {
      const status = JSON.parse(await fs.readFile(file, "utf-8"));
      return NextResponse.json(status);
    } catch {
      // try next path
    }
  }
  return NextResponse.json({ ok: false, error: "目录同步状态暂不可用" }, { status: 404 });
}
