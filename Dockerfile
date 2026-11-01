# syntax=docker/dockerfile:1
# Two stages: resolve and install the locked dependencies with uv, then copy only
# the virtualenv into a slim runtime image that runs as an unprivileged user.

FROM python:3.15-slim AS build
# uv is pinned; installed from PyPI so the build needs no extra registry.
RUN pip install --no-cache-dir uv==0.7.10
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
# Dependencies first (cached unless the lock changes), then the workspace sources.
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY packages/sdk/pyproject.toml packages/sdk/
COPY cli/pyproject.toml cli/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package homelab-harness
COPY packages packages
COPY cli cli
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package homelab-harness

FROM python:3.15-slim AS runtime
RUN groupadd --system --gid 10001 harness \
    && useradd --system --uid 10001 --gid harness --no-create-home harness
COPY --from=build /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HH_HOST=0.0.0.0 \
    HH_PORT=8080
USER harness
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]
CMD ["homelab-harness"]
