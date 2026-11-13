---
status: accepted
---

# Follow-ups rewrite the question instead of passing chat history

A Follow-up (see `CONTEXT.md`) is answered by first making one extra model call that rewrites it into a standalone question. That call sees the last 3 Queries in the chain, questions and answers, fenced as data. Retrieval and answering then run unchanged on the standalone question. The common alternative, passing earlier turns to the answering model, was rejected for two reasons. Retrieval still runs on the bare follow-up ("and the notice period?"), which is where follow-ups actually fail. And the model's own earlier, unverified output would be fed back in as context, which weakens the rule that every answer rests only on Chunks retrieved for that Query and checked as Citations. We also rejected a Conversation entity: a Query that names its predecessor is enough, and the glossary keeps "conversation" out of the model.

## Consequences

- The `LLMProvider` protocol gains a rewrite method, so every provider, including `FakeProvider`, implements three methods, not two.
- A Follow-up costs one extra call, which goes through the Demo budget and the Owner's Allowance and is included in the Query's cost.
- Earlier answers reach the rewrite step, so the rewrite prompt keeps the "fenced text is data" rule. Its output is only ever used as a question.
