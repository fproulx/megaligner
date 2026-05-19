#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
app_path="$project_root/build/macos/MEGAligner.app"
dist_dir="$project_root/dist"
version=$(awk -F '"' '/^version = / { print $2; exit }' "$project_root/pyproject.toml")
arch=$(uname -m)
zip_path="$dist_dir/MEGAligner-$version-macos-$arch.zip"

sh "$script_dir/build_macos_app.sh"

if [ -n "${NOTARY_PROFILE:-}" ] && [ -z "${CODESIGN_IDENTITY:-}" ]; then
  printf '%s\n' "NOTARY_PROFILE requires CODESIGN_IDENTITY for Developer ID signing." >&2
  exit 2
fi

if [ -n "${CODESIGN_IDENTITY:-}" ]; then
  codesign --force --deep --options runtime --sign "$CODESIGN_IDENTITY" "$app_path"
elif [ "${SKIP_CODESIGN:-0}" != "1" ]; then
  codesign --force --deep --sign - "$app_path"
fi

mkdir -p "$dist_dir"
rm -f "$zip_path"
ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"

if [ -n "${NOTARY_PROFILE:-}" ]; then
  xcrun notarytool submit "$zip_path" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$app_path"
  rm -f "$zip_path"
  ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"
fi

printf '%s\n' "Packaged $zip_path"
