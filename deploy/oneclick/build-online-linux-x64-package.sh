#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT_DIR="$ROOT/release"
RELEASE_DATE="${RELEASE_DATE:-$(date +%Y%m%d)}"
NAME="quake-report-online-linux-x64-$RELEASE_DATE"
STAGE="$OUT_DIR/$NAME"
ARCHIVE="$OUT_DIR/$NAME.tar.gz"
INSTALLERS="$OUT_DIR/installers"

rm -rf "$STAGE" "$ARCHIVE"
mkdir -p "$STAGE/.installers" "$INSTALLERS"

node_version="${NODE_VERSION:-v22.23.1}"
node_base="https://nodejs.org/dist/$node_version"
node_file="node-$node_version-linux-x64.tar.gz"
[ -f "$INSTALLERS/$node_file" ] || curl -fL "$node_base/$node_file" -o "$INSTALLERS/$node_file"
miniforge_version="${MINIFORGE_VERSION:-26.3.2-3}"
[ -f "$INSTALLERS/Miniforge3-Linux-x86_64.sh" ] || curl -fL "https://github.com/conda-forge/miniforge/releases/download/$miniforge_version/Miniforge3-Linux-x86_64.sh" -o "$INSTALLERS/Miniforge3-Linux-x86_64.sh"

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
cp "$INSTALLERS/Miniforge3-Linux-x86_64.sh" "$STAGE/.installers/"
cp "$ROOT/deploy/oneclick/start-online-linux-x64.sh" "$STAGE/START-LINUX.sh"
cp "$ROOT/deploy/oneclick/README-online.md" "$STAGE/README.md"
chmod +x "$STAGE/START-LINUX.sh"
printf 'release_date=%s\ngit_commit=%s\nnode=%s\nminiforge=%s\n' \
  "$RELEASE_DATE" "$(git -C "$ROOT" rev-parse HEAD)" "$node_version" "$miniforge_version" > "$STAGE/PACKAGE_INFO.txt"

cd "$OUT_DIR"
COPYFILE_DISABLE=1 tar -czf "$ARCHIVE" "$NAME"
echo "$ARCHIVE"
