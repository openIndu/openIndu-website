# Architecture — Version Endpoint

## Phase 0 finding

No existing `/version` endpoint. `FastAPI(version="0.1.0")` is hardcoded in `web_app.py:99`. Dockerfile has no `GIT_COMMIT`/`BUILD_TIME` env injection.

## Decision

Add `@app.get("/api/v1/version")` in `web_app.py` (same file as `/health` — both are lightweight meta endpoints). Read from env vars with fallback to `app.version`.

## Response format

Must follow the repo's convention: `{"code": 200, "message": "ok", "data": {...}}` (NOT `{"status": "ok", "timestamp": ...}` — the pilot gap #2 fix: architect reads existing conventions before proposing).

## Env vars

| Var | Fallback | Source |
|---|---|---|
| `APP_VERSION` | `app.version` ("0.1.0") | FastAPI constructor |
| `GIT_COMMIT` | `"unknown"` | Dockerfile `ARG` → `ENV` |
| `BUILD_TIME` | `"unknown"` | Dockerfile `ARG` → `ENV` |

## Coding standards (Python)

Per `reference/coding-standards/python.md`:
- Import `os` at the **top of the file** (not inside the function)
- Type hints on the function signature
- No `print()` — this is a read-only endpoint
