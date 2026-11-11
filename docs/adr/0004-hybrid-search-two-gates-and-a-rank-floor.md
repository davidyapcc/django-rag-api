---
status: proposed
---

# Hybrid search keeps two relevance gates and a rank floor

Retrieval combines vector search with Postgres full-text search so that exact terms (codes, names, ids) that embeddings miss can still be retrieved. A Chunk becomes a candidate if it passes **either** gate: its vector distance is within the provider's `max_distance` (ADR 0003), or it matches the question in full-text search (any term, `english` configuration) with `ts_rank_cd` at or above a minimum rank. Reciprocal rank fusion only orders the candidates. We rejected one cut-off on the fused score because RRF scores depend only on rank: no threshold on them means "relevant", so a question with no relevant Chunk would still reach the model instead of Abstaining. We rejected full-text matching that requires every term, because natural questions rarely match all of their words, so the exact-term cases hybrid search exists for would miss. Without a rank floor, any-term matching lets almost every Chunk through.

## Consequences

- There are now two thresholds to tune together with chunk size and the eval: `max_distance` per provider and the minimum text rank.
- `FakeProvider`'s embeddings are already lexical, so the offline eval only guards against regressions (exact-term answered, off-topic Abstains). Evidence that hybrid search helps comes from a manual `run_eval` with the OpenAI provider.
