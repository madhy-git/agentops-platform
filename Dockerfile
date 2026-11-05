# LEARNING NOTES
# - Multi-stage: dependencies install in a builder image; the runtime image gets only the venv, source
#   and data. Smaller image, smaller attack surface (Trivy scans it in CI).
# - The embedding model is downloaded at BUILD time into /opt/models, so running pods need no internet
#   access for it and can use a read-only root filesystem (deploy/k8s).
# - Runs as a non-root user (uid 10001): a container escape lands as an unprivileged account.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --extra otlp --extra aws
COPY src ./src
RUN uv sync --locked --no-dev --extra otlp --extra aws
ENV AGENTOPS_EMBED_CACHE=/opt/models
RUN /app/.venv/bin/python -c "from agentops.rag.embeddings import LocalEmbedder; LocalEmbedder().embed_query('warm up')"

FROM python:3.12-slim
WORKDIR /app
RUN useradd --create-home --uid 10001 app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /opt/models /opt/models
COPY src ./src
COPY prompts ./prompts
COPY policies ./policies
COPY data/policies ./data/policies
COPY data/generated/customers.jsonl ./data/generated/customers.jsonl
ENV PATH="/app/.venv/bin:$PATH" PYDANTIC_AI_NO_BANNER=1 AGENTOPS_EMBED_CACHE=/opt/models HF_HUB_OFFLINE=1
USER app
EXPOSE 8000
CMD ["uvicorn", "agentops.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
