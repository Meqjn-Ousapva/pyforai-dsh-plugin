#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
arch="$(uname -m)"

case "$arch" in
  x86_64|amd64) bin="$here/bin/pyforai-linux-amd64" ;;
  aarch64|arm64) bin="$here/bin/pyforai-linux-arm64" ;;
  *) echo "unsupported architecture: $arch" >&2; exit 1 ;;
esac

if [ ! -f "$bin" ]; then
  echo "missing $bin; run 'make static' first" >&2
  exit 1
fi

target_dir="${PYFORAI_INSTALL_DIR:-/usr/local/bin}"
target="$target_dir/pyforai"

if [ ! -d "$target_dir" ]; then
  mkdir -p "$target_dir" 2>/dev/null || sudo mkdir -p "$target_dir"
fi
if [ -w "$target_dir" ]; then
  install -m 0755 "$bin" "$target"
elif [ "$(id -u)" -eq 0 ]; then
  install -m 0755 "$bin" "$target"
else
  sudo install -m 0755 "$bin" "$target"
fi

echo "installed $target"
"$target" --version
