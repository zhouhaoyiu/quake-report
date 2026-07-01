import { expect, test } from "bun:test";
import { POST } from "../src/app/api/quake/pdf/route";

test("pdf route rejects oversized base64 docx requests before conversion", async () => {
  const req = new Request("http://localhost/api/quake/pdf", {
    method: "POST",
    headers: { "content-length": "100000000" },
    body: "{}",
  });

  const res = await POST(req);
  expect(res.status).toBe(413);
});
