.DEFAULT_GOAL := help

IMAGE ?= docx-bitext-aligner:local
UV_VERSION ?= 0.11.15
MODEL ?= sentence-transformers/LaBSE
HF_CACHE ?= $(CURDIR)/.hf-cache
WORKERS ?= 1
SAMPLE_SIZE ?= 12
ALLOW_MODEL_DOWNLOAD ?= 1
DRY_RUN ?= 0
DEVICE ?= auto
PROFILE ?= 0
ALIGN_ARGS ?=
DOCKER_BUILD_PROGRESS ?= plain
FORCE_BUILD ?= 0

ALIGN_POSITIONAL := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

.PHONY: help build ensure-image align align-dockerized batch app dist-macos test

help:
	@printf '%s\n' 'Usage:'
	@printf '%s\n' '  Double-click Align.command'
	@printf '%s\n' '      macOS guided launcher; no command typing needed.'
	@printf '%s\n' ''
	@printf '%s\n' '  make align'
	@printf '%s\n' '      Runs with uv on the host; opens native macOS dialogs for paths.'
	@printf '%s\n' ''
	@printf '%s\n' '  make align /path/to/docx-dir /path/to/output.tmx'
	@printf '%s\n' '      Detects every bitext pair in the directory and writes one combined TMX file.'
	@printf '%s\n' ''
	@printf '%s\n' '  make align DIR=/path/to/docx-dir OUT=/path/to/output.tmx'
	@printf '%s\n' '      Same as above; better for paths containing spaces.'
	@printf '%s\n' ''
	@printf '%s\n' '  make align-dockerized DIR=/path/to/docx-dir OUT=/path/to/output.tmx'
	@printf '%s\n' '      Runs the same workflow inside Docker.'
	@printf '%s\n' ''
	@printf '%s\n' '  make app'
	@printf '%s\n' '      Builds build/macos/MEGAligner.app, a small native macOS wrapper.'
	@printf '%s\n' ''
	@printf '%s\n' '  make dist-macos'
	@printf '%s\n' '      Builds a GitHub-release-ready macOS app zip in dist/.'
	@printf '%s\n' ''
	@printf '%s\n' 'Useful variables:'
	@printf '%s\n' '  UV_VERSION=0.11.15'
	@printf '%s\n' '  MODEL=sentence-transformers/LaBSE'
	@printf '%s\n' '  WORKERS=2'
	@printf '%s\n' '  DEVICE=auto|cpu|mps|cuda'
	@printf '%s\n' '  PROFILE=1'
	@printf '%s\n' '  DRY_RUN=1'
	@printf '%s\n' '  FORCE_BUILD=1'
	@printf '%s\n' '  ALIGN_ARGS="--src-lang en --tgt-lang ru --pattern auto"'
	@printf '%s\n' ''
	@printf '%s\n' '  make test'
	@printf '%s\n' '      Runs dependency-light unit tests for pair discovery.'

build:
	@sh scripts/build_image.sh "$(IMAGE)" "$(DOCKER_BUILD_PROGRESS)" 1

ensure-image:
	@sh scripts/build_image.sh "$(IMAGE)" "$(DOCKER_BUILD_PROGRESS)" "$(FORCE_BUILD)"

align:
	@RUNNER="native" \
	  UV_VERSION="$(UV_VERSION)" \
	  MODEL="$(MODEL)" \
	  HF_CACHE="$(HF_CACHE)" \
	  WORKERS="$(WORKERS)" \
	  SAMPLE_SIZE="$(SAMPLE_SIZE)" \
	  ALLOW_MODEL_DOWNLOAD="$(ALLOW_MODEL_DOWNLOAD)" \
	  DRY_RUN="$(DRY_RUN)" \
	  DEVICE="$(DEVICE)" \
	  PROFILE="$(PROFILE)" \
	  ALIGN_ARGS="$(ALIGN_ARGS)" \
	  DIR="$(DIR)" \
	  OUT="$(OUT)" \
	  sh scripts/make_align.sh $(ALIGN_POSITIONAL)

align-dockerized: ensure-image
	@RUNNER="docker" \
	  IMAGE="$(IMAGE)" \
	  UV_VERSION="$(UV_VERSION)" \
	  MODEL="$(MODEL)" \
	  HF_CACHE="$(HF_CACHE)" \
	  WORKERS="$(WORKERS)" \
	  SAMPLE_SIZE="$(SAMPLE_SIZE)" \
	  ALLOW_MODEL_DOWNLOAD="$(ALLOW_MODEL_DOWNLOAD)" \
	  DRY_RUN="$(DRY_RUN)" \
	  DEVICE="$(DEVICE)" \
	  PROFILE="$(PROFILE)" \
	  ALIGN_ARGS="$(ALIGN_ARGS)" \
	  DIR="$(DIR)" \
	  OUT="$(OUT)" \
	  sh scripts/make_align.sh $(ALIGN_POSITIONAL)

batch: ensure-image
	@if [ -z "$(DIR)" ] || [ -z "$(OUT_DIR)" ]; then \
	  printf '%s\n' 'Usage: make batch DIR=/path/to/docx-dir OUT_DIR=/path/to/output-dir'; \
	  exit 2; \
	fi
	@mkdir -p "$(OUT_DIR)" "$(HF_CACHE)"
	@docker run --rm -it \
	  -v "$(DIR):/data/input:ro" \
	  -v "$(OUT_DIR):/data/out" \
	  -v "$(HF_CACHE):/models/huggingface" \
	  "$(IMAGE)" /data/input /data/out \
	    --model "$(MODEL)" \
	    --workers "$(WORKERS)" \
	    --device "$(DEVICE)" \
	    $(if $(filter 1,$(ALLOW_MODEL_DOWNLOAD)),--allow-model-download,) \
	    $(if $(filter 1,$(PROFILE)),--profile,) \
	    $(ALIGN_ARGS)

app:
	@sh scripts/build_macos_app.sh

dist-macos:
	@sh scripts/package_macos_app.sh

test:
	@python3 -B -m unittest discover -s tests

%:
	@:
