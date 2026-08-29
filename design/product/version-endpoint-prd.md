# PRD — Version Endpoint

## Context

No `/version` endpoint. Ops/DevOps need to verify which build is deployed (version + git commit + build time) without SSH-ing into the container.

## Goals

- `GET /api/v1/version` returns 200 + `{code: 200, message: "ok", data: {version, git_commit, build_time}}`
- Values from env vars (`APP_VERSION`, `GIT_COMMIT`, `BUILD_TIME`); fallback to app's hardcoded version for `APP_VERSION`

## Non-goals

- Dependency checks (already in /health)
- Auto-detection of git commit at runtime (injected at build time via Dockerfile ARG)

## Acceptance criteria

1. `GET /api/v1/version` → 200 + `{code: 200, message: "ok", data: {version, git_commit, build_time}}`
2. No auth required
3. Follows the repo's `{code, message, data}` response convention (NOT a custom format)
