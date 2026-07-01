import { randomUUID } from "crypto";

type StoredReportFile = {
  buffer: Buffer;
  fileName: string;
  mime: string;
  expires: number;
};

const TTL_MS = 30 * 60 * 1000;
export const MAX_REPORT_FILES = 64;
export const MAX_REPORT_FILE_BYTES = 32 * 1024 * 1024;
export const MAX_REPORT_STORE_BYTES = 128 * 1024 * 1024;

const store: Map<string, StoredReportFile> =
  ((globalThis as any).__quakeReportFileStore ||= new Map<string, StoredReportFile>());

function cleanupExpired() {
  const now = Date.now();
  for (const [id, file] of store) {
    if (file.expires <= now) store.delete(id);
  }
}

function storeBytes() {
  let total = 0;
  for (const file of store.values()) total += file.buffer.length;
  return total;
}

function evictUntilFits(incomingBytes: number) {
  if (incomingBytes > MAX_REPORT_FILE_BYTES) {
    throw new RangeError(`临时文件过大，最大允许 ${MAX_REPORT_FILE_BYTES} 字节`);
  }

  let total = storeBytes();
  while ((store.size >= MAX_REPORT_FILES || total + incomingBytes > MAX_REPORT_STORE_BYTES) && store.size > 0) {
    const oldest = store.keys().next().value as string | undefined;
    if (!oldest) break;
    const file = store.get(oldest);
    if (file) total -= file.buffer.length;
    store.delete(oldest);
  }

  if (total + incomingBytes > MAX_REPORT_STORE_BYTES) {
    throw new RangeError("临时文件缓存空间不足");
  }
}

export function putReportFile(buffer: Buffer, fileName: string, mime: string) {
  cleanupExpired();
  evictUntilFits(buffer.length);
  const id = randomUUID();
  store.set(id, {
    buffer,
    fileName,
    mime,
    expires: Date.now() + TTL_MS,
  });
  return id;
}

export function getReportFile(id: string) {
  cleanupExpired();
  const file = store.get(id);
  if (!file) return null;
  file.expires = Date.now() + TTL_MS;
  store.delete(id);
  store.set(id, file);
  return file;
}
