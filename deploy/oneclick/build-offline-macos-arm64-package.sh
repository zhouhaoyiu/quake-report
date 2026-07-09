#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$ROOT/release"
RELEASE_DATE="${RELEASE_DATE:-$(date +%Y%m%d)}"
NAME="quake-report-offline-macos-arm64-$RELEASE_DATE"
STAGE="$OUT_DIR/$NAME"
ARCHIVE="$OUT_DIR/$NAME.tar.gz"

BASE_PACKAGE="${BASE_PACKAGE:-$(find "$OUT_DIR" -maxdepth 1 -type d -name 'quake-report-offline-macos-arm64-*' ! -name "$NAME" | sort | tail -n 1)}"
NODE_RUNTIME="${NODE_RUNTIME:-$BASE_PACKAGE/.runtime/node}"
PY_RUNTIME="${PY_RUNTIME:-$BASE_PACKAGE/.runtime/python}"
LIBREOFFICE_APP="${LIBREOFFICE_APP:-/Applications/LibreOffice.app}"

[ -x "$NODE_RUNTIME/bin/node" ] || { echo "missing node runtime: $NODE_RUNTIME"; exit 1; }
[ -x "$PY_RUNTIME/bin/python" ] || { echo "missing python runtime: $PY_RUNTIME"; exit 1; }
[ -x "$LIBREOFFICE_APP/Contents/MacOS/soffice" ] || { echo "missing LibreOffice: $LIBREOFFICE_APP"; exit 1; }
[ -f "$ROOT/data/cartopy/shapefiles/natural_earth/physical/ne_50m_land.shp" ] || { echo "missing offline Natural Earth data"; exit 1; }
[ -d "$ROOT/node_modules" ] || { echo "missing node_modules; run npm install once on this Mac"; exit 1; }

rm -rf "$STAGE" "$ARCHIVE"
mkdir -p "$STAGE"

rsync -a \
  --exclude '.git' \
  --exclude '.next' \
  --exclude '.runtime' \
  --exclude '.venv' \
  --exclude '.cache' \
  --exclude 'node_modules' \
  --exclude 'release' \
  --exclude '.DS_Store' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '*.log' \
  --exclude 'scripts/pgv_intensity_map.py' \
  --exclude 'scripts/extract_osm_context.sh' \
  "$ROOT/" "$STAGE/"

cp "$ROOT/deploy/oneclick/start-linux-macos.sh" "$STAGE/START-MAC-LINUX.command"
cp "$ROOT/deploy/oneclick/README.md" "$STAGE/README.md"
chmod +x "$STAGE/START-MAC-LINUX.command"

rsync -a "$ROOT/node_modules/" "$STAGE/node_modules/"
(
  cd "$STAGE"
  PATH="$NODE_RUNTIME/bin:$PATH" NEXT_TELEMETRY_DISABLED=1 npm run build
)
rm -rf "$STAGE/node_modules" "$STAGE/.next/cache"

mkdir -p "$STAGE/.runtime"
printf 'Darwin-arm64\n' > "$STAGE/.runtime/platform.txt"
rsync -a "$NODE_RUNTIME/" "$STAGE/.runtime/node/"
rsync -a "$LIBREOFFICE_APP/" "$STAGE/.runtime/LibreOffice.app/"

PACKER="$PY_RUNTIME/bin/conda-pack"
if [ ! -x "$PACKER" ]; then
  "$PY_RUNTIME/bin/python" -m pip install conda-pack
fi
"$PY_RUNTIME/bin/python" "$PACKER" -p "$PY_RUNTIME" -o "$OUT_DIR/python-runtime.tar.gz" --force
mkdir -p "$STAGE/.runtime/python"
tar -xzf "$OUT_DIR/python-runtime.tar.gz" -C "$STAGE/.runtime/python"
rm -f "$OUT_DIR/python-runtime.tar.gz"
printf 'release_date=%s\ngit_commit=%s\nnode=%s\nlibreoffice=%s\n' \
  "$RELEASE_DATE" "$(git -C "$ROOT" rev-parse HEAD)" "$($NODE_RUNTIME/bin/node -v)" \
  "$($LIBREOFFICE_APP/Contents/MacOS/soffice --version | head -n 1)" > "$STAGE/PACKAGE_INFO.txt"

cd "$OUT_DIR"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" "$NAME"
echo "$ARCHIVE"
