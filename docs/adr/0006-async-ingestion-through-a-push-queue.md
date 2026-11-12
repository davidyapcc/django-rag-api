---
status: proposed
---

# Ingestion runs through a push queue

Supersedes ADR 0002 once accepted. An upload is validated and its text extracted inside the request, the Document is stored as pending, and chunking plus embedding run in a task that Upstash QStash delivers back to the app as a signed HTTP request. ADR 0002 rejected a queue because a conventional one needs a worker and a broker, which the free Render deployment doesn't have. A push queue needs neither: the work runs inside an ordinary request on the existing web service, and QStash provides retries. We chose QStash over Cloud Tasks to stay on Render, and over a Postgres-backed queue because that needs a worker process. Code talks to it through Django's tasks framework, so tests, CI, the eval and local development use `ImmediateBackend` and stay offline, and switching queue vendors is one backend class.

## Consequences

- A Document has a lifecycle (pending, ready, failed), and both front doors handle a Document that isn't ready yet. Its Chunks and its `ready` status still commit together in one transaction.
- The callback is a public endpoint. It trusts only QStash's signature, takes nothing from the payload except the Document id, and is safe to receive more than once.
- Spend can move between upload and callback, so the Demo budget and the Allowance are checked at both points.
- Each callback is still one request, so the upload size cap stays. Larger files would need ingestion split into batches.
- The extracted text is stored on the Document, so re-embedding (for example after an `EMBEDDING_DIM` change) no longer needs the original files.
- Unverified when written: whether Render's free tier throttles CPU after a response, and which QStash free-plan limits and features apply. Confirm both when implementing.
