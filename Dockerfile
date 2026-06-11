# ticktick-mcp — container image for the unofficial TickTick MCP server.
#
# Slim Python base, installed from pyproject, run as a non-root user over HTTP.
# No secrets are baked in — credentials come from the environment at runtime
# (see compose.yaml / .env). The session-token cache lives on a mounted volume.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the package (and its deps) from source. README.md is referenced by
# pyproject's `readme`, so it must be present at build time.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY ticktick_mcp ./ticktick_mcp
RUN pip install .

# Run as an unprivileged user; /data holds the persisted token cache.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data
USER appuser

# Container defaults: serve over HTTP and cache the token on the /data volume.
# Override any of these via the environment. NEVER bake credentials here.
ENV TICKTICK_MCP_TRANSPORT=http \
    TICKTICK_MCP_HOST=0.0.0.0 \
    TICKTICK_MCP_PORT=8000 \
    TICKTICK_TOKEN_CACHE=/data/session.json \
    XDG_CACHE_HOME=/data

EXPOSE 8000

ENTRYPOINT ["ticktick-mcp"]
