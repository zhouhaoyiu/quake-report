#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$ROOT/release"
RELEASE_DATE="${RELEASE_DATE:-$(date +%Y%m%d)}"
NAME="quake-report-online-windows-x64-$RELEASE_DATE"
STAGE="$OUT_DIR/$NAME"
ZIP="$OUT_DIR/$NAME.zip"
INSTALLERS="$OUT_DIR/installers"

rm -rf "$STAGE" "$ZIP"
mkdir -p "$STAGE/.installers" "$INSTALLERS"

node_version="${NODE_VERSION:-v22.23.1}"
node_base="https://nodejs.org/dist/$node_version"
node_file="node-$node_version-win-x64.zip"
[ -f "$INSTALLERS/$node_file" ] || curl -fL "$node_base/$node_file" -o "$INSTALLERS/$node_file"
miniforge_version="${MINIFORGE_VERSION:-26.3.2-3}"
[ -f "$INSTALLERS/Miniforge3-Windows-x86_64.exe" ] || curl -fL "https://github.com/conda-forge/miniforge/releases/download/$miniforge_version/Miniforge3-Windows-x86_64.exe" -o "$INSTALLERS/Miniforge3-Windows-x86_64.exe"

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

cp "$INSTALLERS/$node_file" "$STAGE/.installers/"
cp "$INSTALLERS/Miniforge3-Windows-x86_64.exe" "$STAGE/.installers/"
cp "$ROOT/deploy/oneclick/start-windows.bat" "$STAGE/START-WINDOWS.bat"
cp "$ROOT/deploy/oneclick/start-online-windows-x64.ps1" "$STAGE/start-windows.ps1"
cp "$ROOT/deploy/oneclick/README-online.md" "$STAGE/README.md"
printf 'release_date=%s\ngit_commit=%s\nnode=%s\nminiforge=%s\n' \
  "$RELEASE_DATE" "$(git -C "$ROOT" rev-parse HEAD)" "$node_version" "$miniforge_version" > "$STAGE/PACKAGE_INFO.txt"

cd "$OUT_DIR"
COPYFILE_DISABLE=1 zip -qr "$ZIP" "$NAME"
echo "$ZIP"
