#!/bin/bash
exec 2>&1
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUILD_DIR="/tmp/build_fullstack_${BUILD_ID:-local}"
PACKAGE_FILE="${BUILD_DIR}.tar.gz"

cd "$PROJECT_DIR"
export NEXT_TELEMETRY_DISABLED=1

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

bun install --frozen-lockfile
bun run build

if [ -d ".next/standalone" ]; then
	cp -r .next/standalone "$BUILD_DIR/next-service-dist/"
fi

if [ -d ".next/static" ]; then
	mkdir -p "$BUILD_DIR/next-service-dist/.next"
	cp -r .next/static "$BUILD_DIR/next-service-dist/.next/"
fi

if [ -d "public" ]; then
	cp -r public "$BUILD_DIR/next-service-dist/"
fi

cp -r scripts "$BUILD_DIR/next-service-dist/"
cp -r data "$BUILD_DIR/next-service-dist/"
if [ -d "deploy" ]; then
	cp -r deploy "$BUILD_DIR/"
fi
rm -rf "$BUILD_DIR/next-service-dist/download"
mkdir -p "$BUILD_DIR/next-service-dist/download"

if [ -f "Caddyfile" ]; then
	cp Caddyfile "$BUILD_DIR/"
fi

cp "$SCRIPT_DIR/start.sh" "$BUILD_DIR/start.sh"
chmod +x "$BUILD_DIR/start.sh"

cd "$BUILD_DIR"
tar -czf "$PACKAGE_FILE" .
echo "Build package: $PACKAGE_FILE"
ls -lh "$PACKAGE_FILE"
