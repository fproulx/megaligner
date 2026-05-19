#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd -P)
cd "$project_root"

die() {
  printf '%s\n' "$*" >&2
  exit 2
}

cancel() {
  printf '%s\n' "Cancelled."
  exit 0
}

has_macos_dialogs() {
  [ "$(uname -s)" = "Darwin" ] && command -v osascript >/dev/null 2>&1
}

choose_input_dir() {
  osascript -e 'POSIX path of (choose folder with prompt "Choose the folder containing the paired DOCX files")' 2>/dev/null
}

choose_output_file() {
  osascript -e 'POSIX path of (choose file name with prompt "Choose where to write the TMX file" default name "aligned.tmx")' 2>/dev/null
}

confirm_alignment() {
  if has_macos_dialogs; then
    osascript -e 'display dialog "Discovery finished. Proceed with alignment?" buttons {"Cancel", "Align"} default button "Align" cancel button "Cancel" with icon caution' >/dev/null 2>&1
    return $?
  fi

  printf '%s' 'Proceed with alignment? [y/N] '
  read answer || answer=""
  case "$answer" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

posix_abs_dir() {
  [ -d "$1" ] || die "Input directory not found: $1"
  (cd "$1" && pwd -P)
}

posix_abs_file() {
  case "$1" in
    /*) path="$1" ;;
    *) path="$(pwd)/$1" ;;
  esac
  parent=$(dirname "$path")
  name=$(basename "$path")
  [ -n "$name" ] || die "Output file name is empty"
  mkdir -p "$parent"
  parent=$(cd "$parent" && pwd -P)
  printf '%s/%s\n' "$parent" "$name"
}

if [ "$#" -eq 2 ]; then
  input_dir="$1"
  output_file="$2"
elif [ -n "${DIR:-}" ] && [ -n "${OUT:-}" ]; then
  input_dir="$DIR"
  output_file="$OUT"
elif [ "$#" -eq 0 ]; then
  if ! has_macos_dialogs; then
    die "No paths supplied and macOS osascript dialogs are unavailable. Use: make align DIR=/path/to/docx-dir OUT=/path/to/output.tmx"
  fi
  input_dir=$(choose_input_dir) || cancel
  output_file=$(choose_output_file) || cancel
else
  die "Usage: make align [DOCX_DIR OUT_TMX] or make align DIR=/path/to/docx-dir OUT=/path/to/output.tmx"
fi

input_dir=$(posix_abs_dir "$input_dir")
output_file=$(posix_abs_file "$output_file")
output_dir=$(dirname "$output_file")
output_name=$(basename "$output_file")
hf_cache=${HF_CACHE:-$project_root/.hf-cache}
mkdir -p "$hf_cache"
hf_cache=$(cd "$hf_cache" && pwd -P)
uv_cache=${UV_CACHE_DIR:-$project_root/.uv-cache}
mkdir -p "$uv_cache"
uv_cache=$(cd "$uv_cache" && pwd -P)
uv_version=${UV_VERSION:-0.11.15}
runner=${RUNNER:-native}
model=${MODEL:-sentence-transformers/LaBSE}
workers=${WORKERS:-1}
sample_size=${SAMPLE_SIZE:-12}
device=${DEVICE:-auto}
uv_cmd=""

case "$output_name" in
  *.tmx|*.TMX) ;;
  *) printf '%s\n' "Warning: output file does not end in .tmx; writing TMX content to $output_name" >&2 ;;
esac

download_arg=""
if [ "${ALLOW_MODEL_DOWNLOAD:-1}" = "1" ]; then
  download_arg="--allow-model-download"
fi

profile_arg=""
if [ "${PROFILE:-0}" = "1" ]; then
  profile_arg="--profile"
fi

if [ -t 0 ] && [ -t 1 ]; then
  docker_tty="-it"
else
  docker_tty="-i"
fi

run_aligner() {
  mode=$1
  shift
  case "$mode" in
    docker)
      docker run --rm $docker_tty \
        -v "$input_dir:/data/input:ro" \
        -v "$output_dir:/data/out" \
        -v "$hf_cache:/models/huggingface" \
        "${IMAGE:-docx-bitext-aligner:local}" "$@"
      ;;
    native)
      if [ -z "$uv_cmd" ]; then
        uv_cmd=$(UV_VERSION="$uv_version" sh "$script_dir/bootstrap_uv.sh")
      fi
      HF_HOME="$hf_cache" \
        SENTENCE_TRANSFORMERS_HOME="$hf_cache" \
        UV_CACHE_DIR="$uv_cache" \
        "$uv_cmd" run --locked align-docx "$@"
      ;;
    *)
      die "Unknown runner: $mode"
      ;;
  esac
}

printf '%s\n' "Input directory: $input_dir"
printf '%s\n' "Output TMX:      $output_file"
printf '%s\n' "Runner:          $runner"
printf '%s\n' ""
printf '%s\n' "Previewing detected pairs..."

if [ "$runner" = "docker" ]; then
  align_input=/data/input
  align_output_dir=/data/out
  align_output_file="/data/out/$output_name"
else
  align_input=$input_dir
  align_output_dir=$output_dir
  align_output_file=$output_file
fi

run_aligner "$runner" "$align_input" "$align_output_dir" \
    --combined-output "$align_output_file" \
    --model "$model" \
    --workers "$workers" \
    --sample-size "$sample_size" \
    --device "$device" \
    --dry-run \
    ${ALIGN_ARGS:-}

if [ "${DRY_RUN:-0}" = "1" ]; then
  printf '%s\n' "DRY_RUN=1 set; stopping after preview."
  exit 0
fi

if ! confirm_alignment; then
  cancel
fi

printf '%s\n' ""
printf '%s\n' "Starting alignment..."
printf '%s\n' "Preparing the language model. On the first run, the large model download can take a short while to appear."
printf '%s\n' ""

set -- "$align_input" "$align_output_dir" \
  --combined-output "$align_output_file" \
  --model "$model" \
  --workers "$workers" \
  --sample-size "$sample_size" \
  --device "$device" \
  --yes \
  --force \
  --suppress-discovery-report

if [ -n "$download_arg" ]; then
  set -- "$@" "$download_arg"
fi
if [ -n "$profile_arg" ]; then
  set -- "$@" "$profile_arg"
fi
if [ -n "${ALIGN_ARGS:-}" ]; then
  # Preserve Makefile-style extra arguments such as:
  # ALIGN_ARGS="--src-lang en --tgt-lang ru --batch-size 128"
  set -- "$@" ${ALIGN_ARGS}
fi

run_aligner "$runner" "$@"

printf '%s\n' "Wrote: $output_file"
