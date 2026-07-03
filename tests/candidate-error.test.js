import { expect, test } from "bun:test";
import { candidatePublicError } from "../src/app/api/quake/candidates/route";

test("candidate errors do not expose server command details", () => {
  const message = candidatePublicError(new Error(
    "Command failed: /opt/quake-runtime/conda/bin/python /opt/quake-report/scripts/search_usgs_catalog.py --spec-json {...}",
  ));

  expect(message).toBe("候选匹配失败，请手动确认参数后继续生成");
  expect(message).not.toContain("/opt/");
  expect(message).not.toContain("--spec-json");
});
