---
status: accepted
---

# Hybrid search keeps two relevance gates and a coverage floor

Retrieval combines vector search with Postgres full-text search so that exact terms (codes, names, ids) that embeddings miss can still be retrieved. A Chunk becomes a candidate if it passes **either** gate: its vector distance is within the provider's `max_distance` (ADR 0003), or it contains at least `RAG_MIN_TEXT_COVERAGE` (default 0.6) of the question's terms (`english` stems, stopwords dropped). Reciprocal rank fusion (k = 60) only orders the candidates; full-text matches are ranked by coverage, then `ts_rank_cd`.

We rejected one cut-off on the fused score because RRF scores depend only on rank: no threshold on them means "relevant", so a question with no relevant Chunk would still reach the model instead of Abstaining. We rejected requiring every term, because natural questions rarely match all of their words. We first chose a floor on `ts_rank_cd` and rejected it when measured: Postgres ranks have no IDF, so a question about one rare term matched once ("What is WPS?", 0.1) scores the same as an off-topic question sharing one common word, while the share of the question's terms found separates them (1.0 against 0.17–0.33 on the eval corpus).

## Consequences

- There are now two thresholds to tune together with chunk size and the eval: `max_distance` per provider and `RAG_MIN_TEXT_COVERAGE`.
- At 0.6 a two-term question must match both terms. A long question built around one exact term can fall below the floor and relies on the vector gate, which real embeddings handle for long questions.
- `FakeProvider`'s embeddings are already lexical, so the offline eval only guards regressions: an exact-term question must be answered, and an off-topic question sharing a word must Abstain (it fails at a floor of 0.1). Evidence that hybrid search helps comes from a manual `run_eval` with the OpenAI provider.
