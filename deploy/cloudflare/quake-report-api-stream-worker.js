import { connect } from "cloudflare:sockets";

const ORIGIN_HOST = "59.110.227.22";

function headerEnd(bytes) {
  for (let i = 0; i < bytes.byteLength - 3; i += 1) {
    if (bytes[i] === 13 && bytes[i + 1] === 10 && bytes[i + 2] === 13 && bytes[i + 3] === 10) return i;
  }
  return -1;
}

function parseHttpHead(bytes) {
  const split = headerEnd(bytes);
  if (split < 0) return null;
  const head = new TextDecoder().decode(bytes.slice(0, split));
  const [statusLine, ...lines] = head.split("\r\n");
  const status = Number(statusLine.split(" ")[1]) || 502;
  const headers = new Headers();
  for (const line of lines) {
    const at = line.indexOf(":");
    if (at < 0) continue;
    const name = line.slice(0, at).trim();
    if (/^(connection|transfer-encoding)$/i.test(name)) continue;
    headers.append(name, line.slice(at + 1).trim());
  }
  return { status, headers, bodyStart: split + 4 };
}

async function proxyToAliyun(request) {
  const incoming = new URL(request.url);
  const body = request.method === "GET" || request.method === "HEAD" ? new Uint8Array() : new Uint8Array(await request.arrayBuffer());
  const lines = [
    `${request.method} ${incoming.pathname}${incoming.search} HTTP/1.0`,
    `Host: ${ORIGIN_HOST}`,
    "Connection: close",
    `Accept: ${request.headers.get("accept") || "*/*"}`,
    `User-Agent: ${request.headers.get("user-agent") || "quake-report-api-stream"}`,
    `X-Forwarded-Host: ${incoming.host}`,
    "X-Forwarded-Proto: https",
  ];
  const contentType = request.headers.get("content-type");
  if (contentType) lines.push(`Content-Type: ${contentType}`);
  if (body.byteLength) lines.push(`Content-Length: ${body.byteLength}`);
  lines.push("", "");

  const socket = connect({ hostname: ORIGIN_HOST, port: 80 });
  await socket.opened;
  const writer = socket.writable.getWriter();
  await writer.write(new TextEncoder().encode(lines.join("\r\n")));
  if (body.byteLength) await writer.write(body);
  writer.releaseLock();

  const reader = socket.readable.getReader();
  let headBuffer = new Uint8Array();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return new Response(`Bad origin response: ${headBuffer.byteLength} bytes`, { status: 502 });

    const merged = new Uint8Array(headBuffer.byteLength + value.byteLength);
    merged.set(headBuffer);
    merged.set(value, headBuffer.byteLength);
    const parsed = parseHttpHead(merged);
    if (!parsed) {
      headBuffer = merged;
      continue;
    }

    const firstBody = merged.slice(parsed.bodyStart);
    parsed.headers.set("x-quake-report-cf", "api-stream");
    parsed.headers.set("x-accel-buffering", "no");
    const stream = new ReadableStream({
      async start(controller) {
        if (firstBody.byteLength) controller.enqueue(firstBody);
        try {
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
          controller.close();
        } catch (err) {
          controller.error(err);
        } finally {
          reader.releaseLock();
          try { socket.close?.(); } catch {}
        }
      },
    });
    return new Response(stream, { status: parsed.status, headers: parsed.headers });
  }
}

const worker = {
  fetch(request) {
    return proxyToAliyun(request);
  },
};

export default worker;
