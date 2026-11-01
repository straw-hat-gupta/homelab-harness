# syntax=docker/dockerfile:1
# Two stages: resolve and install the locked dependencies with uv, then copy only
# the virtualenv into a slim runtime image that runs as an unprivileged user.

FROM python:3.13-slim AS build
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
COPY capabilities/proxmox/pyproject.toml capabilities/proxmox/
# Core does not depend on any capability; each is installed next to it and found
# through its entry point. --inexact keeps the first package's environment.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package homelab-harness \
    && uv sync --frozen --no-dev --no-install-workspace --inexact --package homelab-harness-proxmox
COPY packages packages
COPY cli cli
COPY capabilities capabilities
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package homelab-harness \
    && uv sync --frozen --no-dev --no-editable --inexact --package homelab-harness-proxmox

FROM python:3.13-slim AS runtime
RUN groupadd --system --gid 10001 harness \
    && useradd --system --uid 10001 --gid harness --no-create-home harness
COPY --from=build /opt/venv /opt/venv
# OTEL_SEMCONV_STABILITY_OPT_IN: emit the stable HTTP semantic conventions
# (http.server.request.duration in seconds) that the Grafana dashboards query,
# instead of the deprecated names the instrumentation still defaults to.
ENV PATH="/opt/venv/bin:$PATH" \
    OTEL_SEMCONV_STABILITY_OPT_IN=http \
    PYTHONUNBUFFERED=1 \
    HH_HOST=0.0.0.0 \
    HH_PORT=8080
USER harness
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).status == 200 else 1)"]
CMD ["homelab-harness"]
