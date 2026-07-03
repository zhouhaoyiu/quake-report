export interface ParsedQuakeText {
  latitude?: number;
  longitude?: number;
  magnitude?: number;
  depthKm?: number;
  timeUtc?: string;
  place?: string;
  magType?: string;
  assumedYear?: number;
  missing: string[];
}

const SUPPORTED_MAG_TYPES = new Set(["Mw", "Ms", "Mb", "Ml", "Mww", "M"]);

export function parseQuakeText(input: string, now = new Date()): ParsedQuakeText {
  const text = input.normalize("NFKC").replace(/\s+/g, " ").trim();
  const result: ParsedQuakeText = { missing: [] };
  if (!text) {
    return { ...result, missing: ["纬度", "经度", "震级", "发震时间"] };
  }

  const zhLat = text.match(/([北南])\s*纬\s*([+-]?\d+(?:\.\d+)?)/);
  const zhLon = text.match(/([东西])\s*经\s*([+-]?\d+(?:\.\d+)?)/);
  if (zhLat) result.latitude = signed(Number(zhLat[2]), zhLat[1] === "南");
  if (zhLon) result.longitude = signed(Number(zhLon[2]), zhLon[1] === "西");

  if (result.latitude == null || result.longitude == null) {
    const lat = text.match(/([+-]?\d+(?:\.\d+)?)\s*°?\s*([NS])/i);
    const lon = text.match(/([+-]?\d+(?:\.\d+)?)\s*°?\s*([EW])/i);
    if (lat) result.latitude = signed(Number(lat[1]), lat[2].toUpperCase() === "S");
    if (lon) result.longitude = signed(Number(lon[1]), lon[2].toUpperCase() === "W");
  }

  if (result.latitude == null || result.longitude == null) {
    const pair = text.match(
      /(?:lat(?:itude)?|纬度)\D{0,12}([+-]?\d+(?:\.\d+)?).*?(?:lon(?:gitude)?|经度)\D{0,12}([+-]?\d+(?:\.\d+)?)/i,
    );
    if (pair) {
      result.latitude = Number(pair[1]);
      result.longitude = Number(pair[2]);
    }
  }

  const magTypeMatch = text.match(/\b(Mww|Mw|Ms|Mb|Ml|M)\s*([0-9](?:\.\d+)?)/i);
  if (magTypeMatch) {
    result.magnitude = Number(magTypeMatch[2]);
    const normalizedType = normalizeMagType(magTypeMatch[1]);
    if (normalizedType) result.magType = normalizedType;
  } else {
    const zhMag = text.match(/(?:发生|震级(?:为)?|M=?)\s*([0-9](?:\.\d+)?)\s*(?:级|级地震|地震)?/);
    const enMag = text.match(/magnitude\s*([0-9](?:\.\d+)?)/i);
    const mag = zhMag?.[1] || enMag?.[1];
    if (mag) result.magnitude = Number(mag);
    if (zhMag) result.magType = "M";
  }

  const depth = text.match(/(?:震源深度|深度|focal depth|depth)\s*(?:约|为|approximately|of|:)?\s*([0-9]+(?:\.\d+)?)\s*(?:公里|千米|km)/i);
  if (depth) result.depthKm = Number(depth[1]);

  const parsedTime = parseTimeUtc(text, now);
  result.timeUtc = parsedTime?.timeUtc;
  if (parsedTime?.assumedYear) result.assumedYear = parsedTime.assumedYear;

  const zhPlace = text.match(/(?:在|位于)\s*([^()（）,，。;；]+?)\s*(?:\(|（|发生)/);
  if (zhPlace) {
    result.place = zhPlace[1].trim();
  } else {
    const enPlace = text.match(/(?:near|in|offshore of|off|at)\s+([^.;。]+?)(?:\s+(?:earthquake|with|depth|magnitude|M\d)|[.;。]|$)/i);
    if (enPlace) result.place = enPlace[1].trim();
  }

  if (result.latitude == null) result.missing.push("纬度");
  if (result.longitude == null) result.missing.push("经度");
  if (result.magnitude == null) result.missing.push("震级");
  if (!result.timeUtc) result.missing.push("发震时间");
  return result;
}

function signed(value: number, negative: boolean) {
  return negative ? -Math.abs(value) : Math.abs(value);
}

function normalizeMagType(value: string) {
  const v = value.toLowerCase();
  const normalized = v === "mww" ? "Mww" : v === "mw" ? "Mw" : v === "ms" ? "Ms" : v === "mb" ? "Mb" : v === "ml" ? "Ml" : v === "m" ? "M" : "";
  return SUPPORTED_MAG_TYPES.has(normalized) ? normalized : undefined;
}

function parseTimeUtc(text: string, now: Date): { timeUtc: string; assumedYear?: number } | undefined {
  const iso = text.match(
    /(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?\s*(Z|UTC|GMT|UTC\+8|北京时间)?/i,
  );
  if (iso) {
    const [, y, mo, d, h, mi, s = "0", zone = "UTC"] = iso;
    const offsetHours = /UTC\+8|北京时间/i.test(zone) ? 8 : 0;
    const timeUtc = toIsoUtc(Number(y), Number(mo), Number(d), Number(h), Number(mi), Number(s), offsetHours);
    return timeUtc ? { timeUtc } : undefined;
  }

  const zh = text.match(/(?:(\d{4})\s*年)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*(?:时|点|:)\s*(\d{1,2})?\s*(?:分)?/);
  if (!zh) return undefined;
  const [, y, mo, d, h, mi = "0"] = zh;
  const year = y ? Number(y) : now.getFullYear();
  const offsetHours = /UTC|GMT/i.test(text) && !/北京时间|UTC\+8/i.test(text) ? 0 : 8;
  const timeUtc = toIsoUtc(year, Number(mo), Number(d), Number(h), Number(mi), 0, offsetHours);
  return timeUtc ? { timeUtc, assumedYear: y ? undefined : year } : undefined;
}

function toIsoUtc(year: number, month: number, day: number, hour: number, minute: number, second: number, offsetHours: number) {
  const time = Date.UTC(year, month - 1, day, hour - offsetHours, minute, second);
  if (Number.isNaN(time)) return undefined;
  return new Date(time).toISOString().replace(".000", "");
}
