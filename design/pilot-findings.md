# Pilot Findings — Health Check Endpoint (2026-08-05)

## What was run

First end-to-end SDLC pipeline run on `openIndu-website` (aggregate) using control-tower v5.0.0. Feature: "Add a health-check endpoint GET /api/v1/health returning {status, timestamp}".

Pipeline: business-analyst → product-manager → architect → backend → test.

## What worked

- ✅ Design docs written to `design/{business,product,architecture}/` — each role produced its artifact.
- ✅ Code change applied to `openIndu-backend/app/web_app.py` (enhanced existing endpoint with timestamp).
- ✅ Test written to `openIndu-backend/tests/unit/test_health.py` (3 cases: 200, timestamp, no-auth).
- ✅ `ruff check` passed.
- ✅ The pipeline exposed 5 real gaps (below) — which is the point of a pilot.

## Gaps found

### 1. No "check existing code" before design (PIPELINE GAP — high priority)

**What happened**: business-analyst → product-manager → architect all designed a NEW endpoint, but `web_app.py` already had `/api/v1/health` (line 127). The pipeline only discovered this when the backend agent read the code to implement.

**Fix**: `/design` + `/autopilot` should invoke `codebase-analyst` BEFORE the design phases to scan for existing implementations. The /design skill's step 1 (classify) should include "if the feature might already exist, run codebase-analyst first."

### 2. Design didn't check repo API conventions (DESIGN GAP)

**What happened**: The PRD proposed `{"status": "ok", "timestamp": ...}` but the repo uses `{"code": 200, "message": "ok", "data": {...}}` everywhere. The architect should have read existing API patterns.

**Fix**: The architect agent's startup should include "read existing API response patterns in the target repo before proposing formats."

### 3. Local env lacks project deps (ENV GAP)

**What happened**: `pytest` couldn't run — `ModuleNotFoundError: No module named 'sqlalchemy'`. The conftest imports models which import SQLAlchemy. The local env doesn't have `pip install -r requirements.txt`.

**Fix**: Before a pilot run, set up the dev environment (`pip install -r requirements.txt` or `docker-compose up`). The /launch or /autopilot skill should check this as a RULE 2 precondition.

### 4. Two-repo PR flow (OPERATIONAL GAP — minor)

**What happened**: Design docs live in the aggregate (openIndu-website), code in the submodule (openIndu-backend). Two separate PRs needed. The pipeline handled this correctly (backend agent worked in the submodule), but it adds coordination overhead.

**Note**: This is inherent to the submodule architecture. RULE 11's delivery pipeline handles it (submodule PR → merge → aggregate submodule pointer update). Not a bug, just complexity.

### 5. CLAUDE.md structure section stale (DOC GAP — minor)

**What happened**: The aggregate CLAUDE.md §2 still lists the 4 local agents (backend-developer.md etc.) that were deleted in PR #167. The directory structure section wasn't updated.

**Fix**: Update CLAUDE.md §2 to remove the deleted agents from the structure tree.

## Recommendation (for control-tower v5.0.1)

The #1 gap is the most impactful: add a **codebase-analyst pre-check** step to `/design` + `/autopilot` — before the ideation/design phases, scan the target repo for existing implementations. This prevents "designing something that already exists."

In `/design` skill, add to step 1 (classify):
> If the request is a feature/enhancement (not a brand-new product), invoke `codebase-analyst` to scan the target repo for existing implementations BEFORE the business-analyst phase. If found, adjust the scope (enhance existing, not new build).
