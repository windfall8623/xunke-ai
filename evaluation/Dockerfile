# Runtime dependencies are deliberately isolated from backend/requirements.lock.
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 EVAL_CONTRACTS_DIR=/contracts
RUN groupadd --system --gid 10001 evaluator \
    && useradd --system --uid 10001 --gid evaluator --home /evaluation --no-create-home evaluator
WORKDIR /evaluation
COPY evaluation/pyproject.toml ./pyproject.toml
COPY evaluation/rag_eval ./rag_eval
COPY contracts /contracts
CMD ["python", "-m", "rag_eval.worker"]

FROM base AS ragas
COPY evaluation/requirements-ragas.lock /requirements.lock
RUN python -m pip install --require-hashes -r /requirements.lock \
    && python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check
USER 10001:10001

FROM base AS core
COPY evaluation/requirements.lock /requirements.lock
RUN python -m pip install --require-hashes -r /requirements.lock \
    && python -m pip install --no-deps --no-build-isolation . \
    && python -m pip check
USER 10001:10001
