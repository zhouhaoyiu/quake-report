import { expect, test } from "bun:test";
import {
  getReportFile,
  MAX_REPORT_FILE_BYTES,
  MAX_REPORT_FILES,
  putReportFile,
} from "../src/lib/report-file-store";

test("report file store evicts oldest files when count limit is reached", () => {
  const ids = [];
  for (let i = 0; i <= MAX_REPORT_FILES; i += 1) {
    ids.push(putReportFile(Buffer.from(String(i)), `${i}.txt`, "text/plain"));
  }

  expect(getReportFile(ids[0])).toBeNull();
  expect(getReportFile(ids.at(-1)).buffer.toString()).toBe(String(MAX_REPORT_FILES));
});

test("report file store rejects oversized files", () => {
  expect(() => putReportFile(Buffer.alloc(MAX_REPORT_FILE_BYTES + 1), "too-big.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")).toThrow(RangeError);
});
