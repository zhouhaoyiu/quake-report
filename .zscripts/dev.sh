#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cleanup() {
	if [ -n "${DEV_PID:-}" ] && kill -0 "$DEV_PID" >/dev/null 2>&1; then
		kill "$DEV_PID" >/dev/null 2>&1 || true
	fi
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"
command -v bun >/dev/null 2>&1 || { echo "ERROR: bun is not installed or not in PATH"; exit 1; }

bun install
bun run dev &
DEV_PID=$!

for _ in $(seq 1 60); do
	if curl -fsS http://localhost:3000 >/dev/null 2>&1; then
		echo "Next.js dev server is running at http://localhost:3000 (PID: $DEV_PID)."
		disown "$DEV_PID" 2>/dev/null || true
		unset DEV_PID
		exit 0
	fi
	sleep 1
done

echo "ERROR: Next.js dev server failed to start within 60 seconds"
exit 1
