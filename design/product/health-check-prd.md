# PRD — Health Check Endpoint

## Context

Backend API has no health probe. K8s liveness/readiness + local dev verification need a lightweight endpoint.

## Goals

- `GET /api/v1/health` returns 200 + `{status: "ok", timestamp: ISO8601}`
- No authentication required
- Response time < 50ms (no DB/external calls)

## Non-goals

- Dependency checks (DB/Milvus/OSS connectivity) — future `/health/deep`
- Auth/rate-limiting — this endpoint is intentionally open

## Acceptance criteria

1. Given the API is running, When `GET /api/v1/health`, Then response is 200 with body `{"status": "ok", "timestamp": "<ISO8601>"}`
2. Given no auth header, When `GET /api/v1/health`, Then response is still 200 (no auth required)
3. Given any registered dependency is down (DB/Milvus), When `GET /api/v1/health`, Then response is still 200 (shallow health, not deep)

## Success metrics

- K8s liveness probe configured on this endpoint
- Response latency p99 < 50ms

## Out of scope

- `/health/deep` (dependency checks)
- Metrics/monitoring dashboard (bi-analyst phase, if needed)
