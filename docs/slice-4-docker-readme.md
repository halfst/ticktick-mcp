# Slice 4 — Docker + compose + README finalize

**Owner:** Codex (Docker/compose infra) / Claude (README prose + framing)
**Depends on:** Slice 3 (working server)
**Why split:** Containerizing a Python MCP server is patternable infra — good Codex work
against an existing template. The README's honest "unofficial / may break / not affiliated"
framing and the secrets/ToS section are judgment and voice — Claude owns those.

## Context

Package the working server to run as a Docker Compose service alongside other self-hosted
MCP servers, and finalize the public-facing README. This is the last slice; after it the
repo is launch-ready.

## Part A — Codex: containerization

1. **`Dockerfile`** — build the `ticktick-mcp` server image. Slim Python 3.11+ base,
   install from `pyproject.toml`, run the MCP server as the entrypoint. Non-root user.
   No secrets baked into the image.

2. **`compose.yaml`** — a service definition that:
   - Builds/runs the image.
   - Passes `TICKTICK_USERNAME`, `TICKTICK_PASSWORD`, and the token-cache path via
     environment (from an `.env` file that is NOT committed).
   - **Persists the token cache** via a named volume or bind mount so login survives
     container restarts (ties to the Slice 1 cache).
   - Matches the conventions of a typical self-hosted MCP compose stack (restart policy,
     sane container name).

3. Confirm a clean `docker compose up` starts the server and it can authenticate using
   env-supplied credentials, writing its token to the persisted cache.

> Codex note: model this on a standard Python-service Dockerfile + compose. The only
> non-boilerplate parts are (a) never baking secrets in, and (b) persisting the token
> cache volume. Get those two right.

## Part B — Claude: README + framing

Finalize `README.md` for a public audience. Must include:

- **What it is:** an unofficial MCP server for TickTick (v2 web API), with the v1 feature
  list (task CRUD, project CRUD, tags, Markdown notes).
- **The honest disclaimer, prominent and early:** uses the **unofficial/reverse-engineered
  v2 API**; **may break without notice**; **not affiliated with, endorsed by, or official
  TickTick/Appest**. Plain language, no weasel words.
- **The all-day date note:** call out that proper date-only (all-day) task handling is a
  headline feature — it's why the project exists — for people who hit the midnight bug in
  other tooling.
- **Setup:** env vars (`.env` from `.env.example`), `docker compose up`, how to wire the
  server into an MCP host.
- **Auth caveat:** username/password login; logins from new IPs may face a captcha/device
  challenge; what to do if that happens.
- **Security note:** credentials live only in env; the token cache is local/gitignored;
  nothing sensitive is committed.
- **License** and a short contributing note.

## Acceptance criteria — done when

- `docker compose up` (with a populated `.env`) starts the server, authenticates, and
  persists the token cache across a restart.
- No secret is present in the image, the compose file, or the repo; `.env` stays ignored.
- The README states the unofficial/not-affiliated framing prominently, documents setup and
  the auth caveat, and explains the all-day feature.
- A newcomer can clone, fill `.env`, `docker compose up`, and connect the server to an MCP
  host using only the README.
