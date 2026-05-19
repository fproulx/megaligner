#!/bin/sh
set -eu

UV_VERSION=${UV_VERSION:-0.11.15}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
install_dir=${UV_INSTALL_DIR:-"$project_root/.local/bin"}
uv_path="$install_dir/uv"

uv_version_of() {
  "$1" --version 2>/dev/null | awk '{print $2}'
}

if [ -n "${UV_BIN:-}" ] && [ -x "$UV_BIN" ]; then
  if [ "$(uv_version_of "$UV_BIN")" = "$UV_VERSION" ]; then
    printf '%s\n' "$UV_BIN"
    exit 0
  fi
  printf '%s\n' "Configured UV_BIN exists but is not uv $UV_VERSION: $UV_BIN" >&2
fi

if [ -x "$uv_path" ] && [ "$(uv_version_of "$uv_path")" = "$UV_VERSION" ]; then
  printf '%s\n' "$uv_path"
  exit 0
fi

if command -v uv >/dev/null 2>&1; then
  system_uv=$(command -v uv)
  if [ "$(uv_version_of "$system_uv")" = "$UV_VERSION" ]; then
    printf '%s\n' "$system_uv"
    exit 0
  fi
  printf '%s\n' "Found uv at $system_uv, but this project pins uv $UV_VERSION; installing a local pinned copy." >&2
fi

case "$(uname -s):$(uname -m)" in
  Darwin:arm64)
    asset="uv-aarch64-apple-darwin.tar.gz"
    expected_sha256="7e5b336108f8576eda1939920ca0a805b4a9a3c3d3eb2f6140e38b7092fbe4f3"
    ;;
  Darwin:x86_64)
    asset="uv-x86_64-apple-darwin.tar.gz"
    expected_sha256="42bca7cc879d117ed7139a0e26de8cab0b6f033ad439a32144f324d1f8580d8c"
    ;;
  Linux:x86_64)
    asset="uv-x86_64-unknown-linux-gnu.tar.gz"
    expected_sha256="b03e572f010bea94a4a52d42671ba72981e12894f71576181a1d26ff68546da7"
    ;;
  Linux:aarch64|Linux:arm64)
    asset="uv-aarch64-unknown-linux-gnu.tar.gz"
    expected_sha256="21a7dd1a03ea17ac0366887455dab15d215b31dba0870dcd65d3714e22f46c81"
    ;;
  *)
    printf '%s\n' "Unsupported platform for automatic uv install: $(uname -s) $(uname -m)" >&2
    printf '%s\n' "Install uv $UV_VERSION manually, then run make align again." >&2
    exit 2
    ;;
esac

command -v curl >/dev/null 2>&1 || {
  printf '%s\n' "curl is required to install uv automatically." >&2
  exit 2
}
command -v tar >/dev/null 2>&1 || {
  printf '%s\n' "tar is required to install uv automatically." >&2
  exit 2
}

download_file() {
  url=$1
  output=$2
  if [ -t 2 ]; then
    curl -fL --progress-bar "$url" -o "$output"
  else
    curl -fsSL "$url" -o "$output"
  fi
}

download_urls="
https://releases.astral.sh/github/uv/releases/download/$UV_VERSION/$asset
https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$asset
"
tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT INT TERM

printf '%s\n' "Installing pinned uv $UV_VERSION locally..." >&2
downloaded=0
for url in $download_urls; do
  if download_file "$url" "$tmp_dir/$asset"; then
    downloaded=1
    break
  fi
done
if [ "$downloaded" != "1" ]; then
  printf '%s\n' "Could not download uv $UV_VERSION for $asset." >&2
  exit 2
fi

if command -v shasum >/dev/null 2>&1; then
  actual_sha256=$(shasum -a 256 "$tmp_dir/$asset" | awk '{print $1}')
elif command -v sha256sum >/dev/null 2>&1; then
  actual_sha256=$(sha256sum "$tmp_dir/$asset" | awk '{print $1}')
else
  printf '%s\n' "shasum or sha256sum is required to verify the uv download." >&2
  exit 2
fi

if [ "$actual_sha256" != "$expected_sha256" ]; then
  printf '%s\n' "uv download checksum mismatch for $asset" >&2
  printf '%s\n' "Expected: $expected_sha256" >&2
  printf '%s\n' "Actual:   $actual_sha256" >&2
  exit 2
fi

tar -xzf "$tmp_dir/$asset" -C "$tmp_dir"
found_uv=$(find "$tmp_dir" -type f -name uv -perm -111 | head -n 1)
[ -n "$found_uv" ] || {
  printf '%s\n' "Downloaded uv archive did not contain an executable uv binary." >&2
  exit 2
}

mkdir -p "$install_dir"
cp "$found_uv" "$uv_path"
chmod 755 "$uv_path"

found_uvx=$(find "$tmp_dir" -type f -name uvx -perm -111 | head -n 1)
if [ -n "$found_uvx" ]; then
  cp "$found_uvx" "$install_dir/uvx"
  chmod 755 "$install_dir/uvx"
fi

if [ "$(uv_version_of "$uv_path")" != "$UV_VERSION" ]; then
  printf '%s\n' "Installed uv, but version check failed." >&2
  exit 2
fi

printf '%s\n' "$uv_path"
