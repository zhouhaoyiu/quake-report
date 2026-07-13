export function getGlobalValue<T>(key: string, create: () => T): T {
  const scope = globalThis as typeof globalThis & Record<string, unknown>;
  const existing = scope[key];
  if (existing !== undefined) return existing as T;
  const value = create();
  scope[key] = value;
  return value;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
