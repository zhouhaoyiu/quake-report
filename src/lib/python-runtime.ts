import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function resolvePythonBinary() {
  if (process.env.PYTHON?.trim()) return process.env.PYTHON.trim();
  const candidates = [
    "/opt/quake-python/env/bin/python",
    path.join(os.homedir(), "miniforge3", "envs", "zhy", "bin", "python"),
    path.join(os.homedir(), "miniconda3", "envs", "zhy", "bin", "python"),
    "/www/server/panel/pyenv/bin/python",
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || "python3";
}
