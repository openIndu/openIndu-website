"""Step 0 pilot: compare chunk_size/overlap configs on a small document sample
before committing to the full 350-document re-embed.

Why this exists
----------------
chunk_size/overlap is the ONE parameter that requires re-embedding if changed
later (everything else — index type, nprobe, threshold — is query-time and
free to retune after data exists, see prod/rag-optimization-design.md §5).
Rather than guess a number, this script:
  1. Downloads + extracts text for a small set of representative documents ONCE
  2. Re-chunks that same text under several candidate (chunk_size, overlap)
     configs, measured in TOKENS via the real BGE-M3 tokenizer (not Python
     string length — the current production chunker's char-based sizing is
     itself an approximation, see design doc §5.2)
  3. Embeds + inserts each config into an isolated TEMPORARY Milvus collection
     (never touches controller_knowledge) using a FLAT index (exact search,
     so results measure chunking quality only, not ANN approximation noise —
     index-type tuning is a separate, later, zero-cost step)
  4. Runs the golden-test-set cases that map to these pilot documents against
     each config, reports top-1 hit rate / grounded rate / avg score
  5. Drops the temporary collection when done

Run from host (needs GPU + .env + OSS access, same as scripts/offline_embed.py):
    MILVUS_HOST=localhost python scripts/rag_chunk_pilot.py
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
QUERIES_PATH = REPO_ROOT / "scripts" / "rag_eval_queries.json"
os.environ.setdefault("HF_HOME", str(REPO_ROOT / "models" / "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

PILOT_COLLECTION = "rag_chunk_pilot_tmp"
GROUNDED_THRESHOLD = 0.7  # mirrors chat_service._FALLBACK_SCORE_THRESHOLD
TOP_K = 5

# doc_id -> golden test case id (scripts/rag_eval_queries.json), one pilot doc per case
PILOT_DOCS = {
    107: "mitsubishi-driver",
    167: "siemens-plc",
    115: "keyence-plc",
    195: "delta-plc",
    236: "fuji-hardware",
    244: "inovance-driver-sv680",
    178: "ckd-driver",
}

# (chunk_size_tokens, overlap_tokens) candidates — see design doc §5.3 for rationale
CONFIGS = [
    (250, 30),   # fact-lookup lower bound, ~12% overlap
    (250, 0),    # same size, no overlap (test 2026-01 "overlap doesn't help" finding)
    (400, 50),   # general "solid starting point", ~12% overlap
    (400, 0),
    (600, 70),   # CJK-range upper-mid, ~12% overlap
    (600, 0),
]


def load_env(path: Path) -> dict:
    cfg: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip()
    return cfg


CFG = load_env(ENV_PATH)
DATABASE_URL = CFG["DATABASE_URL"]
OSS_ENDPOINT = CFG["OSS_ENDPOINT"]
OSS_BUCKET = CFG["OSS_BUCKET"]
OSS_REGION = CFG["OSS_REGION"]
OSS_KEY_ID = CFG["OSS_ACCESS_KEY_ID"]
OSS_KEY_SECRET = CFG["OSS_ACCESS_KEY_SECRET"]
MILVUS_HOST = os.environ.get("MILVUS_HOST") or CFG["MILVUS_HOST"]
MILVUS_PORT = int(CFG.get("MILVUS_PORT", "19530"))


def oss_client():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=OSS_ENDPOINT, aws_access_key_id=OSS_KEY_ID,
        aws_secret_access_key=OSS_KEY_SECRET, region_name=OSS_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"},
                       connect_timeout=15, read_timeout=120, retries={"max_attempts": 3}),
    )


def fetch_pilot_docs() -> list[dict]:
    """Pull doc metadata (brand/category/oss_key/original_name) for pilot IDs."""
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    docs = []
    with conn.cursor() as cur:
        ids = tuple(PILOT_DOCS.keys())
        cur.execute(
            "SELECT id, original_name, brand, category, oss_key FROM documents WHERE id IN %s",
            (ids,),
        )
        cols = [c[0] for c in cur.description]
        docs = [dict(zip(cols, row)) for row in cur.fetchall()]
    conn.close()
    return docs


def extract_pages(doc: dict) -> list[dict]:
    """Download from OSS + extract text per page — same as sync_document()."""
    import fitz
    obj = oss_client().get_object(Bucket=OSS_BUCKET, Key=doc["oss_key"])
    pdf_bytes = obj["Body"].read()
    pdf = fitz.open(stream=io.BytesIO(pdf_bytes), filetype="pdf")
    pages = []
    for i in range(pdf.page_count):
        text = pdf[i].get_text()
        if text and text.strip():
            pages.append({"page": i + 1, "text": text.strip()})
    pdf.close()
    return pages


def tail_by_tokens(text: str, tokenizer, target_tokens: int) -> str:
    """Longest suffix of `text` whose token count doesn't exceed target_tokens."""
    if target_tokens <= 0 or not text:
        return ""
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        suffix = text[-mid:] if mid > 0 else ""
        n = len(tokenizer.encode(suffix)) if suffix else 0
        if n <= target_tokens:
            best = suffix
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def chunk_by_tokens(pages_text: list[dict], tokenizer, chunk_size: int, overlap: int) -> list[dict]:
    """Paragraph-merge chunking, sized by REAL token count (not len(str))."""
    chunks: list[dict] = []
    chunk_id = 0
    for page_info in pages_text:
        paragraphs = [p.strip() for p in page_info["text"].split("\n") if p.strip()]
        current, current_tokens = "", 0
        for para in paragraphs:
            para_tokens = len(tokenizer.encode(para))
            if current_tokens + para_tokens <= chunk_size:
                current = (current + " " + para).strip() if current else para
                current_tokens += para_tokens
            else:
                if current:
                    chunks.append({"text": current, "page": page_info["page"], "chunk_id": chunk_id})
                    chunk_id += 1
                    overlap_text = tail_by_tokens(current, tokenizer, overlap)
                    current = (overlap_text + " " + para).strip() if overlap_text else para
                    current_tokens = len(tokenizer.encode(current))
                else:
                    current, current_tokens = para, para_tokens
        if current:
            chunks.append({"text": current, "page": page_info["page"], "chunk_id": chunk_id})
            chunk_id += 1
    return chunks


def recreate_pilot_collection():
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
    connections.connect(alias="default", host=MILVUS_HOST, port=str(MILVUS_PORT))
    if utility.has_collection(PILOT_COLLECTION):
        utility.drop_collection(PILOT_COLLECTION)
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="document_name", dtype=DataType.VARCHAR, max_length=500),
        FieldSchema(name="brand", dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=50),
        FieldSchema(name="page", dtype=DataType.INT32),
        FieldSchema(name="chunk_id", dtype=DataType.INT32),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
    ]
    schema = CollectionSchema(fields=fields, description="chunk-size pilot — temporary")
    collection = Collection(name=PILOT_COLLECTION, schema=schema)
    # FLAT = exact search, isolates the experiment to chunking quality only
    # (no ANN approximation noise — index type is a separate, later, free tuning step)
    collection.create_index(field_name="embedding", index_params={"metric_type": "COSINE", "index_type": "FLAT", "params": {}})
    return collection


def drop_pilot_collection():
    from pymilvus import utility
    if utility.has_collection(PILOT_COLLECTION):
        utility.drop_collection(PILOT_COLLECTION)


def run_config(chunk_size: int, overlap: int, docs_pages: dict, model, tokenizer, test_cases: list[dict]) -> dict:
    all_chunks = []
    for doc_id, (meta, pages) in docs_pages.items():
        for c in chunk_by_tokens(pages, tokenizer, chunk_size, overlap):
            all_chunks.append({**c, "document_name": meta["original_name"], "brand": meta["brand"], "category": meta["category"]})

    texts = [c["text"][:4096] for c in all_chunks]
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()

    collection = recreate_pilot_collection()
    insert_data = [{
        "text": c["text"][:4096], "document_name": c["document_name"][:500],
        "brand": c["brand"][:50], "category": c["category"][:50],
        "page": c["page"], "chunk_id": c["chunk_id"], "embedding": embeddings[i],
    } for i, c in enumerate(all_chunks)]
    collection.insert(insert_data)
    collection.flush()
    collection.load()

    results = []
    for case in test_cases:
        q_emb = model.encode([case["query"]], normalize_embeddings=True)
        q_emb = q_emb.tolist() if hasattr(q_emb, "tolist") else q_emb
        hits = collection.search(
            data=q_emb, anns_field="embedding",
            param={"metric_type": "COSINE", "params": {}},
            limit=TOP_K, output_fields=["document_name"],
        )
        top_docs = [h.entity.get("document_name") for h in hits[0]]
        top1_score = round(hits[0][0].score, 4) if len(hits[0]) else 0.0
        expected = case["expected_document_contains"]
        top1_hit = bool(top_docs and expected in top_docs[0])
        top_k_hit = any(expected in d for d in top_docs)
        mode = "grounded" if top1_score >= GROUNDED_THRESHOLD else "fallback"
        results.append({"id": case["id"], "top1_score": top1_score, "top1_hit": top1_hit, "top_k_hit": top_k_hit, "mode": mode})

    collection.release()
    n = len(results)
    return {
        "chunk_size": chunk_size, "overlap": overlap,
        "n_chunks_total": len(all_chunks),
        "avg_chunks_per_doc": round(len(all_chunks) / len(docs_pages), 1),
        "top1_hit_rate": round(sum(r["top1_hit"] for r in results) / n, 3),
        "top_k_hit_rate": round(sum(r["top_k_hit"] for r in results) / n, 3),
        "grounded_rate": round(sum(r["mode"] == "grounded" for r in results) / n, 3),
        "avg_top1_score": round(sum(r["top1_score"] for r in results) / n, 3),
        "per_case": results,
    }


def main():
    print("=== Step 0 pilot: chunk_size/overlap comparison ===\n")

    print("Loading BGE-M3 (GPU if available)…")
    import torch
    from sentence_transformers import SentenceTransformer
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer("BAAI/bge-m3", device=device, local_files_only=True)
    tokenizer = model.tokenizer
    print(f"  model ready on {device.upper()}\n")

    print("Fetching pilot document metadata from PG…")
    docs = fetch_pilot_docs()
    print(f"  {len(docs)} docs found (expected {len(PILOT_DOCS)})\n")

    print("Downloading + extracting text from OSS (once, reused across all configs)…")
    docs_pages = {}
    for doc in docs:
        pages = extract_pages(doc)
        docs_pages[doc["id"]] = (doc, pages)
        n_pages = len(pages)
        n_chars = sum(len(p["text"]) for p in pages)
        print(f"  id={doc['id']:4d} {doc['original_name'][:50]:50}  {n_pages:3d} pages  {n_chars:6d} chars")
    print()

    test_data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    case_by_id = {c["id"]: c for c in test_data["positive_cases"]}
    test_cases = [case_by_id[cid] for cid in PILOT_DOCS.values() if cid in case_by_id]
    print(f"Loaded {len(test_cases)} matching golden-test cases\n")

    all_results = []
    for chunk_size, overlap in CONFIGS:
        label = f"chunk_size={chunk_size}tok overlap={overlap}tok"
        print(f"--- {label} ---")
        r = run_config(chunk_size, overlap, docs_pages, model, tokenizer, test_cases)
        all_results.append(r)
        print(f"  chunks: {r['n_chunks_total']} total, {r['avg_chunks_per_doc']}/doc avg")
        print(f"  top1_hit_rate={r['top1_hit_rate']*100:.0f}%  top_k_hit_rate={r['top_k_hit_rate']*100:.0f}%  "
              f"grounded_rate={r['grounded_rate']*100:.0f}%  avg_top1_score={r['avg_top1_score']:.3f}")
        for pc in r["per_case"]:
            flag = "OK" if pc["top1_hit"] else ("~ " if pc["top_k_hit"] else "MISS")
            print(f"    [{flag}] {pc['id']:26} score={pc['top1_score']:.3f} mode={pc['mode']}")
        print()

    drop_pilot_collection()
    print("=== SUMMARY (sorted by top1_hit_rate desc, then avg_top1_score desc) ===")
    ranked = sorted(all_results, key=lambda r: (r["top1_hit_rate"], r["avg_top1_score"]), reverse=True)
    print(f"{'config':28} {'chunks/doc':>10} {'top1_hit':>9} {'topK_hit':>9} {'grounded':>9} {'avg_score':>10}")
    for r in ranked:
        label = f"size={r['chunk_size']} ovl={r['overlap']}"
        print(f"{label:28} {r['avg_chunks_per_doc']:>10} {r['top1_hit_rate']*100:>8.0f}% {r['top_k_hit_rate']*100:>8.0f}% "
              f"{r['grounded_rate']*100:>8.0f}% {r['avg_top1_score']:>10.3f}")

    Path("rag_chunk_pilot_results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nFull results saved to rag_chunk_pilot_results.json")


if __name__ == "__main__":
    main()
