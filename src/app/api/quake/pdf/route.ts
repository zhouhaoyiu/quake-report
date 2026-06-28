import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import path from "path";
import os from "os";
import fs from "fs/promises";
import { getReportFile } from "@/lib/report-file-store";

const PROJECT_ROOT = process.cwd();
const PDF_SCRIPT = path.join(PROJECT_ROOT, "scripts", "quake_report", "pdf_convert.py");

export async function POST(req: NextRequest) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "quake-pdf-"));
  try {
    const body = await req.json();
    const fileName = safeBaseName(String(body.fileName || "report.docx")).replace(/\.docx$/i, ".pdf");

    const docx = path.join(dir, fileName.replace(/\.pdf$/i, ".docx"));
    if (body.docxFileId) {
      const stored = getReportFile(String(body.docxFileId));
      if (!stored) return NextResponse.json({ ok: false, error: "Word 文件已过期，请重新生成报告" }, { status: 404 });
      await fs.writeFile(docx, stored.buffer);
    } else {
      const dataUrl = String(body.docxDataUrl || "");
      const m = dataUrl.match(/^data:[^,]+;base64,(.+)$/);
      if (!m) return NextResponse.json({ ok: false, error: "缺少 Word 文件数据" }, { status: 400 });
      await fs.writeFile(docx, Buffer.from(m[1], "base64"));
    }

    const result = await runPython(PDF_SCRIPT, [docx, "--output-dir", dir]);
    if (result.code !== 0) {
      return NextResponse.json({ ok: false, error: pdfError(result.stderr) }, { status: 500 });
    }
    const pdfPath = result.stdout.trim().split(/\r?\n/).at(-1) || path.join(dir, fileName);
    const data = await fs.readFile(pdfPath);
    return new NextResponse(new Uint8Array(data), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Length": String(data.length),
        "Content-Disposition": `attachment; filename*=UTF-8''${encodeRFC5987(fileName)}`,
        "Cache-Control": "no-store",
      },
    });
  } catch (e: any) {
    return NextResponse.json({ ok: false, error: e?.message || String(e) }, { status: 500 });
  } finally {
    await fs.rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}

function safeBaseName(name: string) {
  return path.basename(name).replace(/[^\w.\-\u4e00-\u9fff]+/g, "_") || "report.pdf";
}

function encodeRFC5987(value: string) {
  return encodeURIComponent(value).replace(/['()*]/g, (char) =>
    `%${char.charCodeAt(0).toString(16).toUpperCase()}`
  );
}

function runPython(script: string, args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const python = process.env.PYTHON || "python3";
    const proc = spawn(python, [script, ...args], { env: { ...process.env, PYTHONUNBUFFERED: "1" } });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (d) => (stdout += d.toString()));
    proc.stderr.on("data", (d) => (stderr += d.toString()));
    proc.on("close", (code) => resolve({ code: code ?? -1, stdout, stderr }));
  });
}

function pdfError(stderr: string) {
  const runtimeError = stderr.match(/RuntimeError:\s*([^\n]+)/);
  return runtimeError?.[1]?.trim() || stderr.split(/\r?\n/).filter(Boolean).at(-1) || "PDF 转换失败";
}
