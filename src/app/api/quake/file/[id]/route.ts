import { NextRequest, NextResponse } from "next/server";
import { getReportFile } from "@/lib/report-file-store";

export async function GET(
  req: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const { id } = await context.params;
  const file = getReportFile(id);
  if (!file) {
    return NextResponse.json({ ok: false, error: "文件已过期，请重新生成报告" }, { status: 404 });
  }

  const url = new URL(req.url);
  const download = url.searchParams.get("download") !== "0";
  const disposition = download ? "attachment" : "inline";

  return new NextResponse(new Uint8Array(file.buffer), {
    headers: {
      "Content-Type": file.mime,
      "Content-Length": String(file.buffer.length),
      "Content-Disposition": `${disposition}; filename*=UTF-8''${encodeRFC5987(file.fileName)}`,
      "Cache-Control": "private, max-age=1800",
    },
  });
}

function encodeRFC5987(value: string) {
  return encodeURIComponent(value).replace(/['()*]/g, (char) =>
    `%${char.charCodeAt(0).toString(16).toUpperCase()}`
  );
}

