#!/bin/sh
set -eu

image=${1:-docx-bitext-aligner:local}
progress=${2:-plain}
force=${3:-0}
stamp=.docker-image.hash

source_hash() {
  find Dockerfile pyproject.toml uv.lock README.md docx_bitext_aligner scripts -type f -print | sort | xargs cksum | cksum | awk '{print $1 "-" $2}'
}

current_hash=$(source_hash)
stamped_hash=""
if [ -f "$stamp" ]; then
  stamped_hash=$(cat "$stamp")
fi

if [ "$force" != "1" ] && [ "$current_hash" = "$stamped_hash" ] && docker image inspect "$image" >/dev/null 2>&1; then
  printf '%s\n' 'Docker image: ok'
  exit 0
fi

if [ "$force" = "1" ]; then
  printf '%s' "Building Docker image ($image)"
elif [ "$current_hash" != "$stamped_hash" ]; then
  printf '%s' "Docker image stale; rebuilding ($image)"
else
  printf '%s' "Docker image missing; building ($image)"
fi

log=$(mktemp)
cleanup() {
  rm -f "$log"
}
trap cleanup EXIT INT TERM

(DOCKER_BUILDKIT=1 docker build --progress="$progress" -t "$image" . >"$log" 2>&1) &
pid=$!

while kill -0 "$pid" 2>/dev/null; do
  printf '%s' '.'
  sleep 2
done

if wait "$pid"; then
  printf '%s\n' "$current_hash" > "$stamp"
  printf '%s\n' ' ok'
else
  printf '%s\n' ' failed'
  cat "$log"
  exit 1
fi
