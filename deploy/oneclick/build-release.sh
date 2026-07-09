#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export RELEASE_DATE="${RELEASE_DATE:-$(date +%Y%m%d)}"

"$ROOT/deploy/oneclick/build-online-windows-x64-package.sh"
"$ROOT/deploy/oneclick/build-online-linux-x64-package.sh"
"$ROOT/deploy/oneclick/build-offline-macos-arm64-package.sh"
