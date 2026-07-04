import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { resolvePythonBinary } from "@/lib/python-runtime";

type Handlers = {
  onStdoutLine?: (line: string) => void;
  onStderrLine?: (line: string) => void;
};

type RunResult = { code: number; stdout: string; stderr: string };

type WorkerState = {
  proc: ChildProcessWithoutNullStreams | null;
  pending: string;
  current: CurrentJob | null;
  queue: CurrentJob[];
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
const state: WorkerState = ((globalThis as any).__quakePythonWorker ||= {
  proc: null,
  pending: "",
  current: null,
  queue: [],
});

export function workerEnabled() {
  return process.env.QUAKE_PYTHON_WORKER === "1";
}

export function workerBusy() {
  return Boolean(state.current || state.queue.length);
}

export function prewarmPythonWorker() {
  if (workerEnabled()) ensureWorker();
}

export function runPythonWorker(args: string[], handlers: Handlers = {}): Promise<RunResult> {
  return new Promise((resolve) => {
    state.queue.push({ id: randomUUID(), args, handlers, stdout: "", stderr: "", resolve });
    pump();
  });
}

export function stopPythonWorker() {
  state.proc?.kill("SIGTERM");
  state.proc = null;
}

function pump() {
  if (state.current || state.queue.length === 0) return;
  ensureWorker();
  const job = state.queue.shift()!;
  state.current = job;
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
  let frame: any;
  try {
    frame = JSON.parse(line);
  } catch {
    if (state.current) state.current.stdout += `${line}\n`;
    return;
  }
  const job = state.current;
  if (!job || frame.type === "ready") return;
  if (frame.type === "stdout") {
    job.stdout += `${frame.line}\n`;
    job.handlers.onStdoutLine?.(frame.line);
    return;
  }
  if (frame.type === "stderr") {
    job.stderr += `${frame.line}\n`;
    job.handlers.onStderrLine?.(frame.line);
    return;
  }
  if (frame.type === "exit") {
    job.resolve({ code: Number(frame.code ?? -1), stdout: job.stdout, stderr: job.stderr });
    state.current = null;
    pump();
  }
}
