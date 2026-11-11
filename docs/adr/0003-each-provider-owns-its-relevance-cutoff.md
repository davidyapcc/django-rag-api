# Each LLM provider owns its relevance cut-off

Retrieval drops any Chunk whose cosine distance exceeds `max_distance`, and when nothing survives the model is never called. That threshold is an attribute of the provider (`LLMProvider.max_distance`), not a single global setting, because distances aren't comparable across embedding models: the OpenAI provider reads `RAG_MAX_DISTANCE` (0.75), while `FakeProvider`'s hashed bag-of-words vectors need 0.95. We rejected one shared threshold because switching provider would silently turn the cut-off into "retrieve nothing" or "retrieve everything".

## Consequences

- Adding a vendor means choosing and tuning its `max_distance` against the eval, not just implementing `embed` and `answer`.
- Chunk size, `max_distance` and the eval thresholds in `run_eval` move together. Changing one means re-running the eval for every provider.
