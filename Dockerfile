# Stub — finalized in Slice 4 (Docker + compose).
#
# Plan: slim Python 3.11+ base, install from pyproject.toml, run the MCP server
# as a non-root user, no secrets baked into the image.
#
# Intentionally minimal until the server entrypoint (Slice 3) exists.
FROM python:3.11-slim
