# Business Analysis — Health Check Endpoint

## Executive summary

**Problem**: The backend API has no health-check endpoint. Container orchestrators (K8s) and monitoring tools need a lightweight `/health` probe to determine liveness/readiness without authentication.

**User**: DevOps / SRE (via K8s probes) + developer (local docker-compose up verification).

**Value**: Enables K8s liveness/readiness probes; eliminates "is the API up?" guesswork; zero auth overhead.

**Recommendation**: Build. Scope: one `GET /api/v1/health` endpoint, no auth, returns `{status: "ok", timestamp: ISO8601}`. Non-goals: dependency checks (DB/Milvus/OSS) — those go in a future `/health/deep` endpoint.

## Risks

1. Exposing server timestamp — minimal (already in HTTP Date header). Mitigated by returning only ISO8601, no timezone details.
2. Rate abuse — minimal (endpoint is cheap). Mitigated by being stateless + lightweight.

## Stakeholders

- User: DevOps/SRE (K8s probes) + developer (local verification)
- Decision-maker: tech lead
