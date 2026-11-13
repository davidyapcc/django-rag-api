---
status: superseded by ADR 0006
---

# Ingestion is synchronous, with an upload size cap

An upload is extracted, chunked, embedded and committed inside the request, and uploads are capped (`MAX_UPLOAD_BYTES`, 2 MB; `GUEST_MAX_UPLOAD_BYTES`, 500 KB for Guests) so that stays within a request's time budget. We rejected a background queue (Celery, Cloud Tasks) for now: the target hosts (Render free tier, Cloud Run) throttle CPU once the response is sent, so in-process background work stalls, and a real queue adds a worker, a broker and a `processing` status the API and UI would have to expose. Synchronous ingestion also means a Document and all of its Chunks commit together or not at all.

## Consequences

- Large documents are refused rather than ingested slowly. Raising the cap trades against request timeouts on the host.
- Moving to a queue is a design change: Documents gain a lifecycle (pending, ready, failed), both front doors (API and web UI) must handle a Document that isn't ready, and the README trade-offs section must be updated.
