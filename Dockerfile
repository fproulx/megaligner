FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HF_HOME=/models/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/models/huggingface

COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY docx_bitext_aligner ./docx_bitext_aligner
RUN uv sync --locked --no-dev --no-editable

ENTRYPOINT ["uv", "run", "--no-sync", "align-docx"]
CMD ["--help"]
