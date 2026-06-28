#!/bin/sh
set -e

BUILD_DIR="$(cd "$(dirname "$0")" && pwd)"
pids=""

cleanup() {
	for pid in $pids; do
		kill "$pid" 2>/dev/null || true
	done
	exit 0
}
trap cleanup INT TERM

cd "$BUILD_DIR"

if [ -f "./next-service-dist/server.js" ]; then
	cd next-service-dist
	export NODE_ENV=production
	export PORT="${PORT:-3000}"
	export HOSTNAME="${HOSTNAME:-0.0.0.0}"
	export QUAKE_USGS_CATALOG_DB="${QUAKE_USGS_CATALOG_DB:-/opt/quake-report-cache/usgs_catalog.sqlite}"
	export QUAKE_USGS_CATALOG_STATUS="${QUAKE_USGS_CATALOG_STATUS:-/opt/quake-report-cache/usgs_catalog_status.json}"
	if [ -z "$PYTHON" ] && [ -x "/opt/quake-python/env/bin/python" ]; then
		export PYTHON="/opt/quake-python/env/bin/python"
	elif [ -z "$PYTHON" ] && [ -x "/www/server/panel/pyenv/bin/python" ]; then
		export PYTHON="/www/server/panel/pyenv/bin/python"
	fi
	if command -v node >/dev/null 2>&1; then
		node server.js &
	elif command -v bun >/dev/null 2>&1; then
		bun server.js &
	else
		echo "ERROR: node or bun is required"
		exit 1
	fi
	pids="$pids $!"
	cd ..
else
	echo "ERROR: ./next-service-dist/server.js not found"
	exit 1
fi

if [ -f "Caddyfile" ] && command -v caddy >/dev/null 2>&1; then
	exec caddy run --config Caddyfile --adapter caddyfile
fi

wait
