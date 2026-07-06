#!/bin/sh
# scripts/install.sh — curl -fsSL <raw-url>/scripts/install.sh | sh
set -e
REPO="cindulasai/photo-curator"
case "$(uname -s)" in
  Darwin) os="macos" ;;
  Linux)  os="linux" ;;
  *) echo "Use install.ps1 on Windows"; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) arch="arm64" ;;
  x86_64)        arch="x86_64" ;;
  *) echo "unsupported arch: $(uname -m)"; exit 1 ;;
esac
asset="photo-curator-${os}-${arch}"
url=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" |
      grep browser_download_url | grep "$asset" | cut -d'"' -f4)
[ -n "$url" ] || { echo "no binary for $asset"; exit 1; }
dest="${HOME}/.local/bin"
mkdir -p "$dest"
curl -fsSL "$url" -o "$dest/photo-curator"
chmod +x "$dest/photo-curator"
echo "Installed to $dest/photo-curator"
case ":$PATH:" in *":$dest:"*) ;; *) echo "Add $dest to your PATH." ;; esac
