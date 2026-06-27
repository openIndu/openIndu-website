"""Offline OSS → Milvus embedding — host CPU/GPU, bypasses the backend sync path.

Why this exists
---------------
The in-process pipeline (app.services.rag_sync_service.sync_document, driven by
the APScheduler job or POST /sync/trigger) repeatedly hung mid-run on the
6 GB-VRAM-under-WSL2 dev box: a stuck CUDA op left the whole cycle wedged with
no per-document timeout, so one bad document blocked the other 70. This script
is the "produce embeddings offline, push vectors to the shared Milvus" half of
the RAG_SYNC_ENABLED=false model (see backend RAG_SYNC_ENABLED docs).

It reproduces the exact chunking / embedding / insert contract of
sync_document(), but:
  * runs the model on GPU when available, falls back to CPU otherwise,
  * reads the BGE-M3 cache already on disk under models/ (no 2.2 GB re-download),
  * downloads each PDF straight from OSS via boto3 get_object (no presigned-URL
    round-trip that expires after 5 min),
  * wraps every document in a hard wall-clock timeout on a daemon thread, so a
    genuine hang fails that one document and the run continues,
  * commits documents.sync_status after each document, so the run is resumable
    — re-running only picks up what is still pending/failed.

Reads connection settings from the aggregate-repo .env (same file the backend
uses). Nothing here writes application code state beyond documents.sync_status /
sync_time and the Milvus collection.

Usage
-----
  python scripts/offline_embed.py --status            # counts only, no changes
  python scripts/offline_embed.py --clean             # reset failed→pending, purge failed sync_logs (guarded)
  python scripts/offline_embed.py --run --limit 2     # embed 2 docs (smoke test)
  python scripts/offline_embed.py --run               # embed all pending+failed
"""
import argparse
import io
import os
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
# Point HuggingFace at the cache the docker-compose web-api bind-mounts
# (./models:/models). Must be set before sentence_transformers is imported.
os.environ.setdefault("HF_HOME", str(REPO_ROOT / "models" / "huggingface"))
# GPU is used when available (auto-detected below); falls back to CPU otherwise.
# Silence the tokenizers fork warning.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Per-document hard ceiling. On GPU a large PDF encodes in well under this;
# anything past it is treated as a hang, failed, and skipped.
DOC_TIMEOUT_SECONDS = int(os.environ.get("DOC_TIMEOUT_SECONDS", "600"))
# Chunking parameters — MUST match app.services.rag_sync_service.sync_document
# so offline-produced vectors are indistinguishable from scheduler-produced ones.
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
ENCODE_BATCH_SIZE = int(os.environ.get("ENCODE_BATCH_SIZE", "32"))


# --------------------------------------------------------------------------- #
# .env loading (no python-dotenv dependency on the host)
# --------------------------------------------------------------------------- #
def load_env(path: Path) -> dict:
    cfg: dict[str, str] = {}
    if not path.exists():
        sys.exit(f"FATAL: .env not found at {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        cfg[key.strip()] = val.strip()
    return cfg


CFG = load_env(ENV_PATH)
DATABASE_URL = CFG["DATABASE_URL"]
OSS_ENDPOINT = CFG["OSS_ENDPOINT"]
OSS_BUCKET = CFG["OSS_BUCKET"]
OSS_REGION = CFG["OSS_REGION"]
OSS_KEY_ID = CFG["OSS_ACCESS_KEY_ID"]
OSS_KEY_SECRET = CFG["OSS_ACCESS_KEY_SECRET"]
MILVUS_HOST = CFG["MILVUS_HOST"]
MILVUS_PORT = int(CFG.get("MILVUS_PORT", "19530"))
MILVUS_COLLECTION = CFG.get("MILVUS_COLLECTION", "controller_knowledge")


# --------------------------------------------------------------------------- #
# Hard per-call timeout via a daemon thread. A hung worker leaks one daemon
# thread (won't block process exit) instead of wedging the whole run.
# --------------------------------------------------------------------------- #
def run_with_timeout(fn, timeout_s: int, label: str):
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 — surface anything to caller
            box["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError(f"{label} exceeded {timeout_s}s (treated as hang)")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --------------------------------------------------------------------------- #
# Lazy singletons
# --------------------------------------------------------------------------- #
_oss_client = None
_model = None


def oss_client():
    global _oss_client
    if _oss_client is None:
        import boto3
        from botocore.config import Config
        _oss_client = boto3.client(
            "s3",
            endpoint_url=OSS_ENDPOINT,
            aws_access_key_id=OSS_KEY_ID,
            aws_secret_access_key=OSS_KEY_SECRET,
            region_name=OSS_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                connect_timeout=15,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _oss_client


def model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        print(f"  loading BGE-M3 on {device.upper()} from local cache (one-time) …", flush=True)
        t0 = time.monotonic()
        _model = SentenceTransformer("BAAI/bge-m3", device=device, local_files_only=True)
        print(f"  model ready in {time.monotonic() - t0:.0f}s", flush=True)
    return _model


# --------------------------------------------------------------------------- #
# Core: download → parse → chunk → encode → insert (mirrors sync_document)
# --------------------------------------------------------------------------- #
def chunk_pages(pages_text: list[dict]) -> list[dict]:
    """Paragraph-merge chunking with overlap — identical to sync_document."""
    chunks: list[dict] = []
    chunk_id = 0
    for page_info in pages_text:
        text = page_info["text"]
        page = page_info["page"]
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 1 <= CHUNK_SIZE:
                current_chunk = (current_chunk + " " + para).strip() if current_chunk else para
            else:
                if current_chunk:
                    chunks.append({"text": current_chunk, "page": page, "chunk_id": chunk_id})
                    chunk_id += 1
                    overlap_text = current_chunk[-CHUNK_OVERLAP:] if len(current_chunk) > CHUNK_OVERLAP else ""
                    current_chunk = (overlap_text + " " + para).strip() if overlap_text else para
                else:
                    current_chunk = para
        if current_chunk:
            chunks.append({"text": current_chunk, "page": page, "chunk_id": chunk_id})
            chunk_id += 1
    return chunks


def embed_one(doc: dict, collection) -> int:
    """Process a single document end-to-end. Returns number of chunks inserted.

    `doc` is a dict with keys: id, original_name, brand, category, oss_key.
    Raises on any failure (caller marks the document failed and moves on).
    """
    import fitz  # PyMuPDF

    # 1. Download straight from OSS (bytes in memory; docs are <= 50 MB).
    obj = oss_client().get_object(Bucket=OSS_BUCKET, Key=doc["oss_key"])
    pdf_bytes = obj["Body"].read()

    # 2. Extract text page by page.
    pdf = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
    pages_text = []
    for page_num in range(pdf.page_count):
        text = pdf[page_num].get_text()
        if text and text.strip():
            pages_text.append({"page": page_num + 1, "text": text.strip()})
    pdf.close()
    if not pages_text:
        return 0  # nothing extractable — not a failure

    # 3. Chunk.
    chunks = chunk_pages(pages_text)
    if not chunks:
        return 0

    # 4. Encode (GPU when available, normalized — same contract as sync_document).
    texts = [c["text"] for c in chunks]
    embeddings = model().encode(texts, normalize_embeddings=True, batch_size=ENCODE_BATCH_SIZE)
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()

    # 5. Idempotent insert: delete any prior vectors for this doc, then insert.
    name = doc["original_name"]
    try:
        collection.delete(f'document_name == "{name}"')
    except Exception:
        pass  # nothing to delete on first sync, or collection not loaded (OK)
    insert_data = []
    for i, chunk in enumerate(chunks):
        insert_data.append({
            "text": chunk["text"][:2048],
            "document_name": name[:500],
            "brand": (doc["brand"] or "")[:50],
            "category": (doc["category"] or "")[:50],
            "page": chunk["page"],
            "chunk_id": chunk["chunk_id"],
            "embedding": embeddings[i],
        })
    if insert_data:
        collection.insert(insert_data)
        collection.flush()
    return len(insert_data)


# --------------------------------------------------------------------------- #
# DB helpers (psycopg2 directly — no SQLAlchemy on the host)
# --------------------------------------------------------------------------- #
def db_connect():
    """Connect with TCP keepalives so an idle multi-minute embed doesn't get
    silently dropped by the NodePort / LB in front of the remote Postgres.
    """
    import psycopg2
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def fetch_targets(conn, limit: int | None) -> list[dict]:
    """Documents still needing a sync: pending or failed, published only."""
    sql = (
        "SELECT id, original_name, brand, category, oss_key, sync_status "
        "FROM documents "
        "WHERE sync_status IN ('pending', 'failed') AND is_published = true "
        "ORDER BY id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def mark_doc(conn, doc_id: int, status: str):
    """Resilient single-row status write.

    The smoke run died after a 600s embed because the long-idle psycopg2 conn
    had been dropped by the NodePort in front of the remote Postgres. Catch
    OperationalError / InterfaceError, open a fresh short-lived conn, retry
    once. Returns a usable conn (the original, or a fresh replacement) so the
    caller can keep using it for the next doc.
    """
    import psycopg2
    sql = "UPDATE documents SET sync_status = %s, sync_time = now() WHERE id = %s"
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (status, doc_id))
        conn.commit()
        return conn
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        try:
            conn.close()
        except Exception:
            pass
        fresh = db_connect()
        with fresh.cursor() as cur:
            cur.execute(sql, (status, doc_id))
        fresh.commit()
        return fresh


def print_status(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT sync_status, count(*) FROM documents GROUP BY sync_status ORDER BY 2 DESC")
        print("documents.sync_status:")
        for status, n in cur.fetchall():
            print(f"  {status or '(null)':10} {n}")
        cur.execute("SELECT status, count(*) FROM sync_logs GROUP BY status ORDER BY 2 DESC")
        print("sync_logs.status:")
        for status, n in cur.fetchall():
            print(f"  {status:10} {n}")


# --------------------------------------------------------------------------- #
# Guarded cleanup (multi-column WHERE + BEFORE/AFTER + rowcount + conditional commit)
# --------------------------------------------------------------------------- #
def clean_failures(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents WHERE sync_status = 'failed' AND is_published = true")
        failed_docs_before = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM sync_logs WHERE status = 'failed'")
        failed_logs_before = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM documents WHERE sync_status = 'synced'")
        synced_before = cur.fetchone()[0]

    print("BEFORE:")
    print(f"  documents failed (published) : {failed_docs_before}")
    print(f"  documents synced (untouched) : {synced_before}")
    print(f"  sync_logs failed             : {failed_logs_before}")

    if failed_docs_before == 0 and failed_logs_before == 0:
        print("nothing to clean.")
        return

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET sync_status = 'pending', sync_time = NULL "
            "WHERE sync_status = 'failed' AND is_published = true"
        )
        docs_reset = cur.rowcount
        cur.execute("DELETE FROM sync_logs WHERE status = 'failed'")
        logs_deleted = cur.rowcount
        cur.execute("SELECT count(*) FROM documents WHERE sync_status = 'synced'")
        synced_after = cur.fetchone()[0]

    if docs_reset == failed_docs_before and logs_deleted == failed_logs_before and synced_after == synced_before:
        conn.commit()
        print("AFTER (committed):")
        print(f"  documents reset failed->pending : {docs_reset}")
        print(f"  sync_logs failed deleted        : {logs_deleted}")
        print(f"  documents synced (unchanged)    : {synced_after}")
    else:
        conn.rollback()
        sys.exit(
            f"GUARD TRIPPED — rolled back. reset={docs_reset}/{failed_docs_before} "
            f"logs={logs_deleted}/{failed_logs_before} synced={synced_after}/{synced_before}"
        )


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #
def connect_milvus():
    from pymilvus import Collection, connections, utility
    connections.connect(alias="default", host=MILVUS_HOST, port=str(MILVUS_PORT))
    if not utility.has_collection(MILVUS_COLLECTION):
        sys.exit(f"FATAL: Milvus collection '{MILVUS_COLLECTION}' not found on {MILVUS_HOST}:{MILVUS_PORT}")
    return Collection(MILVUS_COLLECTION)


def run(conn, limit: int | None):
    targets = fetch_targets(conn, limit)
    if not targets:
        print("no pending/failed published documents — nothing to do.")
        return
    print(f"{len(targets)} document(s) to embed ({DOC_TIMEOUT_SECONDS}s/doc cap)\n")

    print("connecting to Milvus …", flush=True)
    # connect + collection-open have a 30s hard cap; load() is best-effort
    # outside the timeout (insert works even when collection is not loaded).
    collection = run_with_timeout(connect_milvus, 30, "milvus connect")
    try:
        collection.load(timeout=5)
    except Exception:
        pass
    model()  # warm the model once up front so per-doc timing is just the doc

    ok = skipped = failed = 0
    for i, doc in enumerate(targets, 1):
        tag = f"[{i}/{len(targets)}] id={doc['id']} {doc['original_name'][:48]}"
        t0 = time.monotonic()
        try:
            n = run_with_timeout(lambda: embed_one(doc, collection), DOC_TIMEOUT_SECONDS, tag)
            dt = time.monotonic() - t0
            if n == 0:
                conn = mark_doc(conn, doc["id"], "synced")
                skipped += 1
                print(f"  {tag}  EMPTY (no text)  {dt:.0f}s", flush=True)
            else:
                conn = mark_doc(conn, doc["id"], "synced")
                ok += 1
                print(f"  {tag}  OK {n} chunks  {dt:.0f}s", flush=True)
        except Exception as e:  # noqa: BLE001
            dt = time.monotonic() - t0
            conn = mark_doc(conn, doc["id"], "failed")
            failed += 1
            print(f"  {tag}  FAILED {dt:.0f}s: {type(e).__name__}: {str(e)[:160]}", flush=True)

    print(f"\ndone: ok={ok} empty={skipped} failed={failed}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="show counts and exit")
    g.add_argument("--clean", action="store_true", help="reset failed->pending + purge failed sync_logs (guarded)")
    g.add_argument("--run", action="store_true", help="embed pending+failed documents")
    ap.add_argument("--limit", type=int, default=None, help="cap number of docs (with --run)")
    args = ap.parse_args()

    print(f"DB     : {DATABASE_URL.rsplit('@', 1)[-1]}")
    print(f"Milvus : {MILVUS_HOST}:{MILVUS_PORT}/{MILVUS_COLLECTION}")
    print(f"OSS    : {OSS_ENDPOINT}/{OSS_BUCKET}\n")

    conn = db_connect()
    try:
        if args.status:
            print_status(conn)
        elif args.clean:
            clean_failures(conn)
        elif args.run:
            run(conn, args.limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
