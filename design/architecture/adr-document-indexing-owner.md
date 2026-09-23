# ADR: Document indexing ownership moves to openIndu-studio

Date: 2026-09-23
Status: Implemented in local code; production cutover pending review and delivery

## Decision

The Website Admin manages document metadata and object storage uploads/downloads. Website Web API and MCP continue reading Milvus for search and chat. Website removes the document sync controls, sync status API fields, sync routes, and in-process OBS/OSS-to-Milvus scheduler. Authentication token and presence cleanup jobs remain in the Web API.

openIndu-studio is the future owner of object-storage-to-Milvus indexing. It must download source documents, verify hashes, parse and embed content, update/delete vectors idempotently, and expose its own job status and retry controls. Studio currently has only local Milvus search tooling; no deployable indexing worker exists yet. No production cutover or claim of automatic indexing is made by this ADR.

## Data contract and migration

- Website `documents` metadata remains the source of document ID, object key, hash, brand, category, series, display name, and publication state. Object storage holds the PDF bytes. Studio must use a read-only metadata contract and scoped object access; its write access is limited to the target Milvus collection and its own job state.
- Studio must reconcile new, changed, renamed, unpublished, and deleted documents. In particular, a Website delete removes the object and DB row, so Studio needs a durable snapshot, tombstone, or equivalent reconciliation mechanism to remove stale vectors. `document_name` alone is not a stable identifier for future updates.
- Collection schema, embedding model, chunking limits, and metadata fields must match Website search consumers before cutover. A full backfill and read-back of document/chunk counts and representative queries are required.
- Until Studio is deployed and verified, uploads and deletes can leave Milvus behind the document catalog. Website does not display a misleading sync status. The historical `sync_status`/`sync_time` columns and `sync_logs` table remain for compatibility and rollback but are not read or written by Website runtime.
- The aggregate repository's `scripts/offline_embed.py` is a legacy, manually invoked recovery tool. It is not part of Website runtime and still uses historical status columns. Retire or migrate it when Studio indexing is operational; do not use it as evidence that Studio takeover is complete.

## Deployment order and rollback

Deploy Admin first so it stops calling the retired routes, then Backend. Keep the old database columns/tables during the transition. If Website indexing must be restored before Studio is ready, roll back the Backend and Admin images together and restore the prior configuration; do not try to infer index completeness from legacy statuses after the new code has run.

This decision supersedes the sync-retention scope of `adr-issue-199-settings-rag-consolidation.md` (approved 2026-09-21). That historical ADR remains unchanged as an audit record. The user requested the new boundary on 2026-09-23 after a code and architecture review.
