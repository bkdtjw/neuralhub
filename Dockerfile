# ---- Stage 1: builder ----
FROM python:3.12-slim-bookworm AS builder

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN python -m venv "$VIRTUAL_ENV"

COPY backend/requirements.txt backend/requirements.txt
COPY pyproject.toml pyproject.toml

# Root pyproject carries runtime dependencies that are not mirrored in
# backend/requirements.txt. Alembic is installed explicitly so the image ships
# the CLI required by Phase 3.2, even though migration files are not present in
# the current repository state yet.
RUN pip install --no-cache-dir \
    -r backend/requirements.txt \
    "croniter>=2.0.0" \
    "markdown>=3.5.0" \
    "alembic>=1.13.0"


# ---- Stage 2: runtime ----
FROM python:3.12-slim-bookworm AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl procps gosu libcap2-bin \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --home-dir /home/appuser --shell /bin/bash appuser

RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @notionhq/notion-mcp-server \
    && rm -rf /var/lib/apt/lists/*

RUN chown -R appuser:appuser /home/appuser

COPY --from=builder --chown=appuser:appuser /opt/venv /opt/venv
RUN python -m playwright install --with-deps chromium && \
    chown -R appuser:appuser /home/appuser
COPY --chown=appuser:appuser backend /app/backend
COPY --chown=appuser:appuser config /app/config
COPY --chown=appuser:appuser agents /app/agents
COPY --chown=appuser:appuser skills /app/skills
COPY --chown=appuser:appuser --chmod=755 entrypoint.sh /app/entrypoint.sh
COPY --chown=appuser:appuser pyproject.toml /app/pyproject.toml

# Create directories that appuser needs to write to at runtime
RUN mkdir -p /app/data/logs /app/reports /app/task_outputs && \
    chown -R appuser:appuser /app/data /app/reports /app/task_outputs

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS api
