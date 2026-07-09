#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/package.json" ]; then
  ROOT="$SCRIPT_DIR"
elif [ -f "$SCRIPT_DIR/../../package.json" ]; then
  ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
else
  echo "找不到项目根目录。请在解压后的项目目录里运行本脚本。"
  read -r -p "按回车退出..." _
  exit 1
fi
cd "$ROOT"

RUNTIME="$ROOT/.runtime"
NODE_HOME="$RUNTIME/node"
PY_PREFIX="$RUNTIME/python"

pause_exit() {
  echo "$1"
  read -r -p "按回车退出..." _
  exit 1
}

need_base() {
  command -v "$1" >/dev/null 2>&1 || pause_exit "缺少系统工具 $1，无法自动下载运行环境。"
}

need_base find

mkdir -p "$ROOT/.cache/matplotlib"

if [ -f "$RUNTIME/platform.txt" ]; then
  EXPECTED_PLATFORM="$(tr -d '\r\n' < "$RUNTIME/platform.txt")"
  CURRENT_PLATFORM="$(uname -s)-$(uname -m)"
  [ "$EXPECTED_PLATFORM" = "$CURRENT_PLATFORM" ] || pause_exit "这个离线包是 $EXPECTED_PLATFORM，当前机器是 $CURRENT_PLATFORM，运行时不能混用。"
fi

ensure_node() {
  [ -x "$NODE_HOME/bin/node" ] || pause_exit "离线包缺少 Node.js 运行时：$NODE_HOME"
  export PATH="$NODE_HOME/bin:$PATH"
  node -v >/dev/null
}

ensure_python() {
  PY="$PY_PREFIX/bin/python"
  [ -x "$PY" ] || pause_exit "离线包缺少 Python/Cartopy 运行时：$PY_PREFIX"
  export PATH="$PY_PREFIX/bin:$PATH"

  if [ -x "$PY_PREFIX/bin/conda-unpack" ] && [ ! -f "$PY_PREFIX/.conda-unpacked" ]; then
    echo "首次启动：正在修正离线 Python 运行环境路径..."
    "$PY_PREFIX/bin/conda-unpack"
    touch "$PY_PREFIX/.conda-unpacked"
  fi

  "$PY" - <<'PY' >/dev/null 2>&1 || pause_exit "Python 地图依赖不完整，请重新生成离线包。"
import pandas, numpy, matplotlib, cartopy, shapefile, requests, docx
PY
}

ensure_node
ensure_python

if [ ! -f ".next/standalone/server.js" ]; then
  if [ -d "node_modules" ] && [ -x "$NODE_HOME/bin/npm" ]; then
    NEXT_TELEMETRY_DISABLED=1 "$NODE_HOME/bin/npm" run build
  else
    pause_exit "离线包缺少预构建服务：.next/standalone/server.js"
  fi
fi

SERVER_JS="$ROOT/.next/standalone/server.js"
if [ ! -f "$SERVER_JS" ]; then
  SERVER_JS="$(find "$ROOT/.next/standalone" -name server.js -type f | head -n 1 || true)"
fi
[ -f "$SERVER_JS" ] || pause_exit "构建完成，但没有找到 .next/standalone/server.js。"

export PYTHON="$PY"
export NODE_ENV=production
export PORT="${PORT:-3100}"
export HOSTNAME="${HOSTNAME:-localhost}"
export NEXT_TELEMETRY_DISABLED=1
export MPLCONFIGDIR="$ROOT/.cache/matplotlib"
export CARTOPY_DATA_DIR="$ROOT/data/cartopy"
export QUAKE_PYTHON_WORKER=1
export QUAKE_OFFLINE=1
export QUAKE_USGS_CATALOG_DB="$ROOT/var/usgs_catalog.sqlite"
export QUAKE_USGS_CATALOG_STATUS="$ROOT/var/usgs_catalog_status.json"
if [ -x "$ROOT/.runtime/LibreOffice.app/Contents/MacOS/soffice" ]; then
  export LIBREOFFICE_BIN="$ROOT/.runtime/LibreOffice.app/Contents/MacOS/soffice"
fi

open_url() {
  url="http://localhost:${PORT}"
  for _ in $(seq 1 60); do
    if node -e "fetch(process.argv[1]).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" "$url" >/dev/null 2>&1; then
      if command -v open >/dev/null 2>&1; then
        open "$url"
      elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$url" >/dev/null 2>&1 || true
      fi
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
