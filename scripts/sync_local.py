"""Trigger an OSS → Milvus sync from the command line.

Use when ``RAG_SYNC_ENABLED=false`` in the running backend (the default) so
sync runs on demand rather than on the hourly scheduler. The CLI talks to
whatever backend ``API`` points to — by default the local docker-compose
web-api, but you can ``API=https://api.openindu.com/api/v1 python …`` to
trigger production from your laptop, which is the whole point of the
"build the embeddings locally, push to remote Milvus" model.

Usage:
  python scripts/sync_local.py                     # trigger + watch until idle
  python scripts/sync_local.py --no-wait           # fire-and-forget
  python scripts/sync_local.py --logs              # show recent sync_logs and exit
  python scripts/sync_local.py --status            # show counts and exit
  API=https://api.openindu.com/api/v1 python scripts/sync_local.py  # remote target

Auth: admin phone + code from the .env (defaults match the docker-compose
init-admin user 13800000000 / 888888).
"""
import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.request import Request

import json

# Defaults match docker-compose. Override via env: API, ADMIN_PHONE, ADMIN_CODE.
API = os.environ.get("API", "http://localhost:8004/api/v1").rstrip("/")
PHONE = os.environ.get("ADMIN_PHONE", "13800000000")
CODE = os.environ.get("ADMIN_CODE", "888888")


def _request(method: str, path: str, *, token: str | None = None, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Surface the server's JSON error message instead of "HTTP Error 401".
        msg = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} -> HTTP {e.code}: {msg}") from None


def login() -> str:
    res = _request("POST", "/auth/login", body={"phone": PHONE, "code": CODE})
    if res.get("code") != 200:
        raise SystemExit(f"login failed: {res}")
    return res["data"]["tokens"]["access_token"]


def show_status(token: str) -> dict:
    res = _request("GET", "/sync/status", token=token)
    return res["data"]


def show_logs(token: str, n: int = 10) -> list[dict]:
    res = _request("GET", f"/sync/logs?page=1&size={n}", token=token)
    return res["data"]["items"]


def trigger(token: str) -> None:
    res = _request("POST", "/sync/trigger", token=token, body={"mode": "incremental"})
    print(f"  triggered: {res.get('message', res)}")


def fmt_status(s: dict) -> str:
    docs = s.get("documents", {})
    pending = s.get("pending_count", "?")
    parts = [f"{k}={v}" for k, v in sorted(docs.items())]
    return f"docs: {', '.join(parts)} | pending+failed={pending}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-wait", action="store_true", help="trigger and exit; don't poll for completion")
    ap.add_argument("--status", action="store_true", help="show sync status and exit")
    ap.add_argument("--logs", action="store_true", help="show last 10 sync_logs and exit")
    ap.add_argument("--poll", type=int, default=10, help="seconds between status polls (default 10)")
    args = ap.parse_args()

    print(f"target: {API}")
    token = login()
    print(f"logged in as {PHONE}")

    if args.logs:
        for row in show_logs(token):
            err = f"  err: {row['error_message'][:120]}" if row.get("error_message") else ""
            print(f"  {row['sync_time']}  {row['action']:>6}/{row['status']:>7}  doc={row.get('document_id') or '-'}{err}")
        return

    before = show_status(token)
    print(f"before: {fmt_status(before)}")

    if args.status:
        return

    trigger(token)
    if args.no_wait:
        print("(--no-wait: queued; check progress with --status / --logs)")
        return

    # Poll: stop when pending_count stops decreasing for two consecutive polls
    # (sync finished), or after a generous safety cap.
    print("watching status — Ctrl+C to detach")
    last_pending = before.get("pending_count", 0)
    stable = 0
    deadline = time.monotonic() + 30 * 60  # 30-minute cap
    while time.monotonic() < deadline:
        time.sleep(args.poll)
        s = show_status(token)
        cur = s.get("pending_count", 0)
        delta = cur - last_pending
        print(f"  {fmt_status(s)}  (Δpending={delta:+d})")
        if cur == last_pending:
            stable += 1
            if stable >= 2:
                print("done — pending count stable for two polls")
                return
        else:
            stable = 0
            last_pending = cur
    print("hit 30-minute safety cap; check --logs for details", file=sys.stderr)


if __name__ == "__main__":
    main()
