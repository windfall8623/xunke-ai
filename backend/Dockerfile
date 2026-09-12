# Build from the repository root: docker build -f backend/Dockerfile .
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${PYTHON_IMAGE} AS dependencies

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY backend/requirements.lock ./requirements.lock
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install --require-hashes -r requirements.lock

# Only the deterministic JSON comparison package is shared with the API.
# Ragas and its conflicting LangChain dependencies live in evaluation/Dockerfile.
COPY evaluation/pyproject.toml ./evaluation/pyproject.toml
COPY evaluation/rag_eval ./evaluation/rag_eval
RUN /opt/venv/bin/python -m pip install --no-deps --no-build-isolation ./evaluation \
    && /opt/venv/bin/python -m pip check

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    DATA_DIR=/app/data \
    EVAL_CONTRACTS_DIR=/contracts \
    TEACH_SKILL_DIR=/opt/xunke/skills/xunke-teach \
    MYSQL_AUTO_INIT=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 xunke \
    && useradd --system --uid 10001 --gid xunke --home /app --no-create-home xunke \
    && mkdir -p /app/data/chroma \
    && chown -R xunke:xunke /app/data

WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=xunke:xunke backend/app ./app
COPY --chown=xunke:xunke backend/migrations ./migrations
COPY --chown=xunke:xunke backend/scripts ./scripts
COPY --chown=xunke:xunke backend/requirements.lock ./requirements.lock
COPY --chown=xunke:xunke contracts /contracts
COPY --chown=xunke:xunke .agents/skills/xunke-teach /opt/xunke/skills/xunke-teach
COPY --chown=xunke:xunke evaluation/requirements.lock evaluation/requirements-ragas.lock ./evaluation-runtime/
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
