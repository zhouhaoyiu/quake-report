import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { resolvePythonBinary } from "@/lib/python-runtime";
import { getGlobalValue, isRecord } from "@/lib/runtime-values";

type Handlers = {
  onQueued?: (position: number) => void;
  onStart?: () => void;
  onStdoutLine?: (line: string) => void;
  onStderrLine?: (line: string) => void;
};

type RunResult = { code: number; stdout: string; stderr: string };

type WorkerState = {
  proc: ChildProcessWithoutNullStreams | null;
  pending: string;
  current: CurrentJob | null;
  queue: CurrentJob[];
  timer: ReturnType<typeof setTimeout> | null;
};

type CurrentJob = {
  id: string;
  args: string[];
  handlers: Handlers;
  stdout: string;
  stderr: string;
  resolve: (result: RunResult) => void;
};

const WORKER_SCRIPT = path.join(process.cwd(), "scripts", "quake_report", "worker.py");
const MAX_JOBS = Math.max(1, Number(process.env.QUAKE_MAX_JOBS || 8));
const JOB_TIMEOUT_MS = Math.max(10_000, Number(process.env.QUAKE_JOB_TIMEOUT_MS || 180_000));
const state = getGlobalValue<WorkerState>("__quakePythonWorker", () => ({
  proc: null,
  pending: "",
  current: null,
  queue: [],
  timer: null,
}));

export function workerEnabled() {
  return process.env.QUAKE_PYTHON_WORKER === "1";
}

export function workerBusy() {
  return Boolean(state.current || state.queue.length);
}

export function prewarmPythonWorker() {
  if (workerEnabled()) ensureWorker();
}

export function runPythonWorker(args: string[], handlers: Handlers = {}, id = randomUUID()): Promise<RunResult> {
  const position = (state.current ? 1 : 0) + state.queue.length + 1;
  if (position > MAX_JOBS) {
    return Promise.resolve({ code: -2, stdout: "", stderr: "生成队列已满，请稍后重试\n" });
  }
  return new Promise((resolve) => {
    state.queue.push({ id, args, handlers, stdout: "", stderr: "", resolve });
    handlers.onQueued?.(position);
    pump();
  });
}

export function cancelPythonWorkerJob(id: string) {
  const index = state.queue.findIndex((job) => job.id === id);
  if (index >= 0) {
    const [job] = state.queue.splice(index, 1);
    job.resolve({ code: -1, stdout: job.stdout, stderr: "任务已取消\n" });
    notifyQueuePositions();
    return;
  }
  if (state.current?.id === id) {
    state.current.stderr += "任务已取消\n";
    state.proc?.kill("SIGTERM");
  }
}

function pump() {
  if (state.current || state.queue.length === 0) return;
  ensureWorker();
  const job = state.queue.shift()!;
  state.current = job;
  notifyQueuePositions();
  job.handlers.onStart?.();
  state.timer = setTimeout(() => {
    if (state.current?.id !== job.id) return;
    state.current.stderr += "生成超时，请缩小查询范围后重试\n";
    state.proc?.kill("SIGKILL");
  }, JOB_TIMEOUT_MS);
  state.proc!.stdin.write(`${JSON.stringify({ id: job.id, args: job.args })}\n`);
}

function ensureWorker() {
  if (state.proc && !state.proc.killed) return;
  const proc = spawn(resolvePythonBinary(), [WORKER_SCRIPT], {
    env: { ...process.env, PYTHONUNBUFFERED: "1", MPLCONFIGDIR: process.env.MPLCONFIGDIR || path.join(os.tmpdir(), "quake-report-mpl") },
  });
  state.proc = proc;
  state.pending = "";
  proc.stdout.on("data", (chunk) => onWorkerStdout(chunk.toString()));
  proc.stderr.on("data", (chunk) => {
    if (state.current) state.current.stderr += chunk.toString();
  });
  proc.on("close", () => {
    clearJobTimer();
    if (state.current) {
      state.current.resolve({ code: -1, stdout: state.current.stdout, stderr: state.current.stderr });
      state.current = null;
    }
    state.proc = null;
    if (state.queue.length) pump();
  });
}

function onWorkerStdout(text: string) {
  state.pending += text;
  const lines = state.pending.split(/\r?\n/);
  state.pending = lines.pop() || "";
  for (const line of lines) handleFrame(line);
}

function handleFrame(line: string) {
  let frame: unknown;
  try {
    frame = JSON.parse(line);
  } catch {
    if (state.current) state.current.stdout += `${line}\n`;
    return;
  }
  if (!isRecord(frame)) return;
  const job = state.current;
  if (!job || frame.type === "ready") return;
  if (frame.type === "stdout") {
    const text = String(frame.line ?? "");
    job.stdout += `${text}\n`;
    job.handlers.onStdoutLine?.(text);
    return;
  }
  if (frame.type === "stderr") {
    const text = String(frame.line ?? "");
    job.stderr += `${text}\n`;
    job.handlers.onStderrLine?.(text);
    return;
  }
  if (frame.type === "exit") {
    clearJobTimer();
    job.resolve({ code: Number(frame.code ?? -1), stdout: job.stdout, stderr: job.stderr });
    state.current = null;
    pump();
  }
}

function clearJobTimer() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
}

function notifyQueuePositions() {
  state.queue.forEach((job, index) => job.handlers.onQueued?.(index + 2));
}
