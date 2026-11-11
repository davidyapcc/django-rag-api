# AGENTS.md

Django + DRF document Q&A API: uploads are chunked, embedded into Postgres/pgvector, and `/ask` answers from them with citations. The README holds the architecture and the design trade-offs, and `docs/adr/` records why the less obvious ones were made. When you change one of those decisions, update its README section in the same change, and supersede its ADR rather than editing it.

## Done means green

A change is done when every gate in `.github/workflows/ci.yml` passes locally: ruff (check + format), mypy, `makemigrations --check`, pytest (coverage floor 90%), and `manage.py run_eval`. Tests and the eval need Postgres with the pgvector extension at `DATABASE_URL` (see `.env.example`); run them with `LLM_PROVIDER=fake`.

## Invariants

- **Tenant isolation.** Every query over `Document`, `Chunk` or `Query` filters by owner. `Chunk.owner` is denormalised so retrieval scopes by owner in the same SQL as the similarity search; set it on every chunk you create. Add a cross-user test for any new endpoint.
- **Citations are verified.** `apps/qa/services.ask` keeps only cited ids that were actually retrieved. Model output never reaches the client unfiltered.
- **Document text is data.** Retrieved chunks go to the model fenced as `<chunk>` and the system prompt says to ignore instructions inside them. Keep both when editing prompts.
- **Spend goes through the Demo budget.** Any new code path that calls the provider calls `budget.ensure_available()` before and `budget.record()` after (see `apps/core/budget.py`).
- **Offline by default.** Tests, CI and the eval run on `FakeProvider`; stub the OpenAI client (see `tests/test_providers.py`) to test provider code. A live API call belongs only in a manual `run_eval` with `LLM_PROVIDER=openai`.

## Layout conventions

- Views stay thin (validate, call a service, map errors to status codes). The API (`apps/*/views.py`) and the web UI (`apps/web/`) are two front doors onto the same services; put rules in the service so both get them. Logic lives in `apps/*/services.py`; provider-agnostic RAG pieces live in `rag/`.
- Domain terms (Owner, Document, Chunk, Query, Citation, Guest, Demo budget) are defined in `CONTEXT.md`; use them in code and copy.
- A new LLM vendor is one class implementing the `LLMProvider` protocol in `rag/providers.py`, plus a branch in `_build`. Each provider owns its `max_distance`, because embedding models differ in scale.
- Model names and token prices are settings fed by env vars, so a price change is a config change.

## Gotchas

- `EMBEDDING_DIM` is baked into the `Chunk.embedding` column. Changing it needs a migration and re-embedding every document.
- Chunk size, `max_distance` and the eval thresholds in `apps/qa/management/commands/run_eval.py` move together: tune retrieval against the eval, and raise a threshold only when the eval clears it with margin.
- Ingestion is synchronous with a size cap on purpose (Render/Cloud Run throttle CPU after the response). Moving it to a queue is a design change: update the README trade-offs too.
- Production settings force HTTPS redirects. The autouse fixture in `tests/conftest.py` disables that and pins the fake provider for every test; keep new test-wide setup there.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `davidyapcc/django-rag-api` (`gh` locally, GitHub MCP tools in cloud sessions). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/` (created lazily). See `docs/agents/domain.md`.
