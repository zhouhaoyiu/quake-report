/**
 * GET /download/:path*
 *
 * 把项目 download/ 下的文件暴露为可下载的 URL。
 */
import { NextRequest, NextResponse } from "next/server";
import path from "path";
import fs from "fs";

const DOWNLOAD_DIR = path.join(process.cwd(), "download");

const MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".csv": "text/csv",
  ".json": "application/json",
};

export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path: parts } = await ctx.params;
    // 防御路径穿越
    const safe = parts
      .map((p) => path.basename(p))
      .filter((p) => p && !p.startsWith("."));
    const filePath = path.join(DOWNLOAD_DIR, ...safe);
    if (!filePath.startsWith(DOWNLOAD_DIR)) {
      return NextResponse.json({ error: "Forbidden" }, { status: 403 });
    }
    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      return NextResponse.json({ error: "Not found" }, { status: 404 });
    }

    const ext = path.extname(filePath).toLowerCase();
    const mime = MIME[ext] || "application/octet-stream";
    const buf = fs.readFileSync(filePath);

    const res = new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": mime,
        "Content-Length": String(buf.length),
        "Cache-Control": "public, max-age=300",
      },
    });
    // PDF 和 docx 直接 inline 预览；图片直接 inline
    return res;
  } catch (e: any) {
    return NextResponse.json(
      { error: e?.message || String(e) },
      { status: 500 }
    );
  }
}
