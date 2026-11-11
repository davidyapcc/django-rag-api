# Async ingestion

Uploads are extracted, chunked, embedded and committed inside the request. There is no background job, job status or ingestion queue.

## Why this is out of scope

The project runs on hosts that throttle CPU once the response is sent (Render free tier, Cloud Run without always-on CPU), so in-process background work stalls. A real queue needs a worker and a broker, which the free deployment doesn't have, and it gives Documents a lifecycle (pending, ready, failed) that both front doors, the API and the web UI, would have to handle. Synchronous ingestion with a size cap also keeps a Document and all of its Chunks committing together or not at all. The full reasoning is in `docs/adr/0002-synchronous-ingestion-with-size-cap.md`.

The "retries" half of the original idea is mostly covered already: the OpenAI client retries transient failures, and a failed ingestion is stored with status `failed` and its error.

## What would reopen it

- Moving to a host with an always-on worker (a paid plan, or Cloud Run with CPU always allocated), **and**
- A real need for uploads larger than the request time budget allows (the cap is 2 MB today).

If both hold, supersede ADR 0002 instead of editing it, and update the README trade-offs.

## Prior requests

- README roadmap: "Async ingestion with a job status and retries" (removed during triage, Nov 2026)
