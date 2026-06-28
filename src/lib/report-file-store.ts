import { randomUUID } from "crypto";

type StoredReportFile = {
  buffer: Buffer;
  fileName: string;
  mime: string;
  expires: number;
};

const TTL_MS = 30 * 60 * 1000;
const store: Map<string, StoredReportFile> =
  ((globalThis as any).__quakeReportFileStore ||= new Map<string, StoredReportFile>());

function cleanupExpired() {
  const now = Date.now();
  for (const [id, file] of store) {
    if (file.expires <= now) store.delete(id);
  }
}

export function putReportFile(buffer: Buffer, fileName: string, mime: string) {
  cleanupExpired();
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
  return file;
}

