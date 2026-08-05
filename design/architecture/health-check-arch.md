# Architecture — Health Check Endpoint

## Decision

Add `GET /api/v1/health` as a new route in `openIndu-backend/app/api/` following the existing FastAPI router pattern.

## Options considered

| Option | Verdict |
|---|---|
| New router `app/api/health.py` + register in `web_app.py` | ✅ Cleanest — follows existing pattern |
| Add to an existing router (e.g. users.py) | ❌ Mixes concerns |
| Middleware-level response | ❅ Overcomplicated for a simple endpoint |

## Design

```
app/api/health.py
  - router = APIRouter()
  - GET /health → {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
  - No auth dependency
  - No DB/session dependency

app/web_app.py
  - app.include_router(health.router, prefix="/api/v1", tags=["health"])
```

## Non-functional

- Latency: < 50ms (no I/O, pure datetime)
- Security: no auth (intentional); no sensitive data exposed
- Observability: endpoint itself will be used BY the liveness probe

## Rollback

Remove the router include + delete `app/api/health.py`. Zero migration.
