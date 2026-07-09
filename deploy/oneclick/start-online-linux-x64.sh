#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RUNTIME="$ROOT/.runtime"
INSTALLERS="$ROOT/.installers"
NODE_HOME="$RUNTIME/node"
CONDA_HOME="$RUNTIME/miniforge"
PY_PREFIX="$RUNTIME/python"

pause_exit() {
  echo "$1"
  read -r -p "按回车退出..." _
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || pause_exit "缺少系统工具 $1。"
}

ensure_node() {
  if [ ! -x "$NODE_HOME/bin/node" ]; then
    need tar
    archive="$(find "$INSTALLERS" -maxdepth 1 -name 'node-v*-linux-x64.tar.gz' | head -n 1)"
    [ -n "$archive" ] || pause_exit "缺少 Node.js Linux x64 安装包。"
    tmp="$RUNTIME/node-extract"
    rm -rf "$tmp" "$NODE_HOME"
    mkdir -p "$tmp"
    tar -xzf "$archive" -C "$tmp"
    mv "$tmp"/* "$NODE_HOME"
    rm -rf "$tmp"
  fi
  export PATH="$NODE_HOME/bin:$PATH"
}

ensure_python() {
  if [ ! -x "$CONDA_HOME/bin/conda" ]; then
    installer="$(find "$INSTALLERS" -maxdepth 1 -name 'Miniforge3-Linux-x86_64.sh' | head -n 1)"
    [ -n "$installer" ] || pause_exit "缺少 Miniforge Linux x64 安装包。"
    bash "$installer" -b -p "$CONDA_HOME"
  fi

  conda="$CONDA_HOME/bin/conda"
  if [ ! -x "$PY_PREFIX/bin/python" ]; then
    "$conda" create -y -p "$PY_PREFIX" -c conda-forge python=3.11
  fi

  PY="$PY_PREFIX/bin/python"
  if [ ! -f "$PY_PREFIX/.quake-deps-ok" ] || ! "$PY" - <<'PY' >/dev/null 2>&1
import pandas, numpy, matplotlib, cartopy, shapefile, requests, docx
PY
  then
    "$conda" install -y -p "$PY_PREFIX" -c conda-forge pandas numpy matplotlib cartopy pyshp requests python-docx
    "$PY" - <<'PY'
import pandas, numpy, matplotlib, cartopy, shapefile, requests, docx
PY
    touch "$PY_PREFIX/.quake-deps-ok"
  fi
}

mkdir -p "$RUNTIME" "$ROOT/.cache/matplotlib"
ensure_node
ensure_python

if [ ! -d "node_modules" ]; then
  npm install --no-audit --no-fund
fi

if [ ! -f ".next/standalone/server.js" ]; then
  NEXT_TELEMETRY_DISABLED=1 npm run build
fi

SERVER_JS="$ROOT/.next/standalone/server.js"
export PYTHON="$PY"
export NODE_ENV=production
export PORT="${PORT:-3100}"
export HOSTNAME="${HOSTNAME:-localhost}"
export NEXT_TELEMETRY_DISABLED=1
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"
export CARTOPY_DATA_DIR="$ROOT/data/cartopy"
export QUAKE_PYTHON_WORKER=1
export QUAKE_USGS_CATALOG_DB="$ROOT/var/usgs_catalog.sqlite"
export QUAKE_USGS_CATALOG_STATUS="$ROOT/var/usgs_catalog_status.json"
unset QUAKE_OFFLINE

echo "正在增量更新 USGS 目录..."
if ! "$PY" scripts/sync_usgs_catalog.py \
  --db "$QUAKE_USGS_CATALOG_DB" \
  --status-json "$QUAKE_USGS_CATALOG_STATUS" \
  --min-mag 3; then
  echo "USGS 目录更新失败，将使用包内现有目录继续启动。"
fi

open_url() {
  url="http://localhost:${PORT}"
  for _ in $(seq 1 60); do
    if node -e "fetch(process.argv[1]).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" "$url" >/dev/null 2>&1; then
      command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1 || true
      return
    fi
    sleep 1
  done
  echo "服务已启动，但浏览器未自动打开：$url"
}

open_url &
echo "启动地震报告系统：http://localhost:${PORT}"
echo "关闭此窗口即可停止服务。"
node "$SERVER_JS"
