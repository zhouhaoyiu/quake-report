import { expect, test } from "bun:test";
import { parseQuakeText } from "../src/lib/quake-text-parser.ts";

test("parses CENC style bulletin text", () => {
  const parsed = parseQuakeText(
    "中国地震台网正式测定：06月25日06时30分，在日本本州东部附近海域(北纬40.20度，东经142.40度)发生6.9级地震，震源深度50公里。",
    new Date("2026-06-30T00:00:00Z"),
  );

  expect(parsed.missing).toEqual([]);
  expect(parsed.latitude).toBe(40.2);
  expect(parsed.longitude).toBe(142.4);
  expect(parsed.magnitude).toBe(6.9);
  expect(parsed.depthKm).toBe(50);
  expect(parsed.timeUtc).toBe("2026-06-24T22:30:00Z");
  expect(parsed.assumedYear).toBe(2026);
  expect(parsed.place).toBe("日本本州东部附近海域");
});

test("does not mark explicit year as assumed", () => {
  const parsed = parseQuakeText(
    "2025年06月25日06时30分，在日本本州东部附近海域(北纬40.20度，东经142.40度)发生6.9级地震，震源深度50公里。",
    new Date("2026-06-30T00:00:00Z"),
  );

  expect(parsed.timeUtc).toBe("2025-06-24T22:30:00Z");
  expect(parsed.assumedYear).toBeUndefined();
});

test("parses yearless CENC examples for candidate fallback", () => {
  const cases = [
    ["中国地震台网正式测定：06月27日21时34分，在阿富汗(北纬36.40度，东经70.80度)发生6.0级地震，震源深度210公里。", 36.4, 70.8, 6.0, 210, "2026-06-27T13:34:00Z", "阿富汗"],
    ["中国地震台网正式测定：06月25日06时04分，在委内瑞拉(北纬10.35度，西经68.35度)发生7.1级地震，震源深度10公里。", 10.35, -68.35, 7.1, 10, "2026-06-24T22:04:00Z", "委内瑞拉"],
    ["中国地震台网正式测定：12月07日04时41分，在美国阿拉斯加州(北纬60.30度，西经139.60度)发生6.9级地震，震源深度10公里。", 60.3, -139.6, 6.9, 10, "2026-12-06T20:41:00Z", "美国阿拉斯加州"],
    ["中国地震台网正式测定：12月21日23时30分，在瓦努阿图群岛(南纬17.75度，东经167.95度)发生6.1级地震，震源深度50公里。", -17.75, 167.95, 6.1, 50, "2026-12-21T15:30:00Z", "瓦努阿图群岛"],
    ["中国地震台网正式测定：12月05日12时02分，在伊朗(北纬31.65度，东经49.50度)发生5.5级地震，震源深度20公里。", 31.65, 49.5, 5.5, 20, "2026-12-05T04:02:00Z", "伊朗"],
    ["中国地震台网正式测定：12月06日02时44分，在美国加利福尼亚州北部沿岸近海(北纬40.40度，西经125.00度)发生7.0级地震，震源深度10公里。", 40.4, -125, 7.0, 10, "2026-12-05T18:44:00Z", "美国加利福尼亚州北部沿岸近海"],
  ];

  for (const [text, latitude, longitude, magnitude, depthKm, timeUtc, place] of cases) {
    const parsed = parseQuakeText(text, new Date("2026-06-30T00:00:00Z"));
    expect(parsed.missing).toEqual([]);
    expect(parsed.latitude).toBe(latitude);
    expect(parsed.longitude).toBe(longitude);
    expect(parsed.magnitude).toBe(magnitude);
    expect(parsed.depthKm).toBe(depthKm);
    expect(parsed.timeUtc).toBe(timeUtc);
    expect(parsed.assumedYear).toBe(2026);
    expect(parsed.place).toBe(place);
  }
});
