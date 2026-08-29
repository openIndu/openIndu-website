---
description: RULE 11 steps ④+⑤ for openIndu-website — build & push openIndu-* Docker images to Aliyun CR, then update infra-deploy yaml tags via a Gitee PR. Project-scoped — assumes the aggregate repo layout (openIndu-backend / openIndu-admin / openIndu-portal submodules) and that the user has docker login to crpi-f7ll8pm177asmofl.cn-chengdu.personal.cr.aliyuncs.com.
disable-model-invocation: true
---

# /release

Build production images for the openIndu submodules, push to Aliyun CR, and
update the K8s manifests in `infra-deploy` so the next `kubectl apply` (or
ArgoCD sync) picks them up. The skill is the release half of the workflow —
it does **not** apply anything to a cluster.

> **Why `/release` and not `/build`**: the control-tower plugin ships its own
> `/build` skill covering RULE 11 step ④ only, with a different tag convention
> and different Dockerfile choices. Two incompatible definitions under one name
> is a footgun, so this repo's ④+⑤ command is named `/release`. Inside this
> aggregate repo, **use `/release`** — the plugin's `/build` does not know about
> `Dockerfile.k8s`, the SHA tag convention, or the infra-deploy step.

## Args

```
/release                # rebuild & push all three: backend, admin, portal
/release backend        # only backend
/release admin portal   # any subset, space-separated
```

Valid components: `backend`, `admin`, `portal`.

## Step 1 — Sanity checks (abort if any fails)

1. Working directory is the aggregate repo root (must contain `openIndu-backend/`, `openIndu-admin/`, `openIndu-portal/`).
2. Each requested submodule has a clean working tree (`git status --short` empty) — uncommitted changes mean the image you'd push doesn't match any commit.
3. `docker info` succeeds (Docker Desktop running).
4. `docker info` shows the user is logged in to `crpi-f7ll8pm177asmofl.cn-chengdu.personal.cr.aliyuncs.com`. If not, tell the user to `docker login` first; do not attempt automated login.

If any check fails, print the reason and stop. Do not partially build.

## Step 2 — Determine versions

For each requested component:

- `cd <submodule>`
- `git fetch origin main --quiet`
- `SHA = git rev-parse --short origin/main` — always use the latest remote main, never a local stale checkout

Cache the SHAs for use in build tags and the yaml update.

## Step 3 — Build each image

Constants:

- `REG = crpi-f7ll8pm177asmofl.cn-chengdu.personal.cr.aliyuncs.com/openindu`

Per component, in this order:

| Component | Build context        | Dockerfile       | Image name         |
| --------- | -------------------- | ---------------- | ------------------ |
| backend   | `./openIndu-backend` | `Dockerfile`     | `openindu-backend` |
| admin     | `./openIndu-admin`   | `Dockerfile.k8s` | `openindu-admin`   |
| portal    | `./openIndu-portal`  | `Dockerfile.k8s` | `openindu-portal`  |

> admin/portal **must** use `Dockerfile.k8s`. The two Dockerfiles bake
> different nginx configs: `Dockerfile` → `nginx.conf`, which proxies
> `/api/` to `http://web-api:8004/api/` for the docker-compose stack;
> `Dockerfile.k8s` → `nginx.k8s.conf`, which serves static files only
> because K8s Ingress routes `/api/` to the `web-api` Service directly.
>
> Note the cluster does have a `web-api` Service on 8004, so the compose
> config would resolve rather than hard-fail — the damage is subtler: the
> frontend pod adds a redundant proxy hop and silently bypasses the Ingress
> routing that the manifests declare. Use `Dockerfile.k8s` regardless.

Build command pattern:

```
docker build -f <Dockerfile> -t $REG/openindu-<comp>:latest -t $REG/openindu-<comp>:<SHA> ./openIndu-<comp>
```

> **Both tags are load-bearing — do not drop `:latest`.** The deployments in
> `infra-deploy/openIndu-website/` pin git short SHAs (`openindu-admin:5097c14`
> etc.), but `rag-server.yaml` pulls `openindu-backend:latest`. Stop pushing
> `latest` and rag-server silently stops tracking backend changes. (The
> control-tower plugin's `/build` says "never use `:latest`" — that rule is
> right in general and wrong for this cluster until rag-server is re-pinned.)
>
> The build context is the **submodule directory**, not the aggregate root —
> each submodule has its own `.dockerignore`, and a root context would drag all
> three submodules plus `models/` into the daemon.

Build sequentially (Docker Desktop on Windows handles parallel poorly). If
any build returns non-zero, stop the whole skill — don't push partial set.

## Step 4 — Push each image

For each component, push both tags. Sequence: small images first (admin,
portal — 100 MB each, < 30 s) then backend (9 GB — first time 5-10 min, later
pushes only the changed layer ~ 10 MB).

```
docker push $REG/openindu-<comp>:latest
docker push $REG/openindu-<comp>:<SHA>
```

Watch for `Layer already exists` — that's the layered Dockerfile working. If
the backend pushes more than ~500 MB on a code-only change, the Dockerfile
tiering is broken; surface this to the user.

If the backend push exceeds ~5 minutes of estimated time (image > 1 GB on
first push), spawn it as a background task and proceed with the yaml update
while it streams. Don't block on backend push completion before generating
the PR — the yaml update only needs the SHA, not a finished push.

## Step 5 — Update infra-deploy yaml via a Gitee PR

The infra-deploy repo lives at `https://gitee.com/openIndu/infra-deploy.git`.
Prefer a sibling checkout at `../infra-deploy` next to the aggregate repo.

1. If `../infra-deploy` doesn't exist, `git clone https://gitee.com/openIndu/infra-deploy.git` into the parent directory.
2. `cd ../infra-deploy && git checkout main && git pull --ff-only origin main`. Bail if it isn't clean.
3. Create a release branch: `git checkout -b release/<utc-date-and-component-list>` (e.g. `release/20260623-backend-admin-portal`). If the branch already exists locally, append `-N` until it's unique.
4. Edit the relevant yaml files with `sed`:
   - backend → `openIndu-website/backend.yaml` line `image: $REG/openindu-backend:<old>` → `:<new-SHA>`
   - admin → `openIndu-website/admin.yaml`
   - portal → `openIndu-website/portal.yaml`
5. Verify the edit with `grep -nE "image:" openIndu-website/*.yaml` and show the user the new lines.
6. `git add openIndu-website && git commit -m "<title>" -m "<body>"`. Commit message format:

   ```
   chore: bump openIndu-website image tags

   - openindu-backend: <old-SHA> -> <new-SHA>     (omit lines for components not built)
   - openindu-admin:   <old-SHA> -> <new-SHA>
   - openindu-portal:  <old-SHA> -> <new-SHA>

   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

7. `git push -u origin release/...`
8. Print the Gitee PR-creation URL with the source/target prefilled:
   `https://gitee.com/openIndu/infra-deploy/pull/new/openIndu:release/<branch>...openIndu:main`
   followed by a one-liner: _"open this link, click 创建 Pull Request, then 合并"_. **Use English in the PR title/body** so PowerShell heredocs don't mangle CJK characters when the user copies them.

   Use the `pull/new/...` form, **not** `compare/main...<branch>` — the compare
   page does not offer a create-PR action, it only renders the diff.

   Never call `git push origin main` on infra-deploy. The `Bash` PreToolUse
   hook guards against `git push.*(main|master)`, but make sure the command
   string you emit doesn't even appear to match — that hook is over-eager and
   has tripped on PR-body text containing "main" in the past.

## Step 6 — Report

End with a single concise summary like:

```
Built & pushed:
  openindu-backend  85330c1     (was 7a273f0)
  openindu-admin    c516bab     (was 0612962)
  openindu-portal   e02b4aa     (was 70ff574)

infra-deploy PR: https://gitee.com/openIndu/infra-deploy/pull/new/openIndu:release/20260623-...openIndu:main

Next:
  - Click 合并 on the Gitee PR.
  - On the K8s box:
      kubectl apply -f openIndu-website/ -n <namespace>
      # or, if ArgoCD: it will sync automatically.
```

## Things this skill must NOT do

- **No `kubectl` calls** — the user holds the cluster, this skill stops at PR-ready.
- **No commits inside the submodules.** Dockerfile / source changes belong in their own feature PR before `/release` runs.
- **No `git push origin main` on infra-deploy.** PR-only, even though the user is the owner; treat it the same as the protected aggregate-repo main.
- **No automatic Gitee PR merge.** There's no Gitee token in this environment; the user clicks merge.
- **No partial push if any build failed.** Either all requested components ship or none.

## Edge cases

- If `git rev-parse origin/main` matches a tag already pulled-and-present in the local Docker image cache (`docker image inspect $REG/openindu-<comp>:<SHA>` succeeds with same digest as registry), still run the build — the registry check is the source of truth; a local cache hit might be stale relative to remote.
- If only `admin` and `portal` are requested and the backend image hasn't changed, the infra-deploy commit must only touch `admin.yaml` and `portal.yaml`. Don't sweep all yamls.
- If the user runs `/release` immediately after another `/release` in the same minute, the release branch name collision (date-based) will hit — append `-2`, `-3` etc.
- If the Aliyun CR namespace ever changes from `openindu`, edit this skill and the Dockerfile tags together — they're coupled.
