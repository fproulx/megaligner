#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
source_dir="$project_root/macos/MEGAligner"
build_dir="$project_root/build/macos"
app_path="$build_dir/MEGAligner.app"
resource_project="$app_path/Contents/Resources/MEGAligner"
icon_source="$source_dir/Assets/AppIcon.png"
iconset_path="$build_dir/MEGAligner.iconset"
module_cache="$build_dir/module-cache"

if [ "$(uname -s)" != "Darwin" ]; then
  printf '%s\n' "The macOS app can only be built on macOS." >&2
  exit 2
fi

if ! command -v swiftc >/dev/null 2>&1; then
  printf '%s\n' "swiftc was not found. Install Xcode Command Line Tools, then run make app again." >&2
  exit 2
fi
if ! command -v sips >/dev/null 2>&1 || ! command -v iconutil >/dev/null 2>&1; then
  printf '%s\n' "sips and iconutil are required to build the macOS app icon." >&2
  exit 2
fi

rm -rf "$app_path"
mkdir -p "$app_path/Contents/MacOS" "$app_path/Contents/Resources" "$module_cache"

cp "$source_dir/Info.plist" "$app_path/Contents/Info.plist"
printf 'APPL????' > "$app_path/Contents/PkgInfo"

CLANG_MODULE_CACHE_PATH="$module_cache" swiftc \
  -O \
  "$source_dir/main.swift" \
  -o "$app_path/Contents/MacOS/MEGAligner"

chmod 755 "$app_path/Contents/MacOS/MEGAligner"

rm -rf "$iconset_path"
mkdir -p "$iconset_path"
sips -z 16 16 "$icon_source" --out "$iconset_path/icon_16x16.png" >/dev/null
sips -z 32 32 "$icon_source" --out "$iconset_path/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$icon_source" --out "$iconset_path/icon_32x32.png" >/dev/null
sips -z 64 64 "$icon_source" --out "$iconset_path/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$icon_source" --out "$iconset_path/icon_128x128.png" >/dev/null
sips -z 256 256 "$icon_source" --out "$iconset_path/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$icon_source" --out "$iconset_path/icon_256x256.png" >/dev/null
sips -z 512 512 "$icon_source" --out "$iconset_path/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$icon_source" --out "$iconset_path/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$icon_source" --out "$iconset_path/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$iconset_path" -o "$app_path/Contents/Resources/MEGAligner.icns"

mkdir -p "$resource_project"

cp "$project_root/pyproject.toml" "$resource_project/pyproject.toml"
cp "$project_root/uv.lock" "$resource_project/uv.lock"
cp "$project_root/LICENSE" "$resource_project/LICENSE"
cp "$project_root/README.md" "$resource_project/README.md"

mkdir -p "$resource_project/docx_bitext_aligner" "$resource_project/scripts"
cp -R "$project_root/docx_bitext_aligner/." "$resource_project/docx_bitext_aligner/"
cp "$project_root/scripts/bootstrap_uv.sh" "$resource_project/scripts/bootstrap_uv.sh"
chmod 755 "$resource_project/scripts/bootstrap_uv.sh"
find "$resource_project" \( -name __pycache__ -o -name '*.pyc' \) -prune -exec rm -rf {} +

printf '%s\n' "Built $app_path"
