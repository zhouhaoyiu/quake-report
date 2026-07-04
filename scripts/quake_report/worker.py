#!/usr/bin/env python3
"""Line-based worker for reusing quake_report imports between jobs."""
from __future__ import annotations

import contextlib
import json
import sys
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from quake_report import cli  # noqa: E402


_stdout = sys.stdout


def _emit(payload: dict) -> None:
    _stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _stdout.flush()


class _LineEmitter:
    def __init__(self, kind: str):
        self.kind = kind
        self.buf = ""

    def write(self, text: str) -> int:
        self.buf += text
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line:
                _emit({"type": self.kind, "line": line})
        return len(text)

    def flush(self) -> None:
        if self.buf:
            _emit({"type": self.kind, "line": self.buf})
            self.buf = ""


def _run(job: dict) -> None:
    job_id = job.get("id")
    out = _LineEmitter("stdout")
    err = _LineEmitter("stderr")
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = int(cli.main(job.get("args") or []) or 0)
        except SystemExit as exc:
            code = int(exc.code or 0)
        except Exception:
            traceback.print_exc()
            code = 1
    out.flush()
    err.flush()
    _emit({"type": "exit", "id": job_id, "code": code})


def main() -> int:
    _emit({"type": "ready"})
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            _run(json.loads(raw))
        except Exception as exc:
            _emit({"type": "exit", "id": None, "code": 1, "error": str(exc)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
